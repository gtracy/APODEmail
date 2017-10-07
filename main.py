import webapp2
import os
import re
import logging
import time
import datetime
import calendar

from google.appengine.api import users
from google.appengine.api import mail
from google.appengine.api import urlfetch
from google.appengine.api.labs.taskqueue import Task

from google.appengine.ext import db
from google.appengine.ext.webapp import template

from google.appengine.runtime import apiproxy_errors

from BeautifulSoup import BeautifulSoup, Tag

import config
from data_model import UserCounter


class MainHandler(webapp2.RequestHandler):
  def get(self):

      # figure out how many people are currently on the distribution list
      counter = db.GqlQuery("SELECT * FROM UserCounter").get()

      # add the counter to the template values
      if counter is None:
          userCount = 0
      else:
          userCount = counter.userCount
      template_values = { 'counter':userCount,'captcha_secret':config.RECAPTCHA_KEY }

      # generate the html
      path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
      self.response.out.write(template.render(path, template_values))

## end MainHandler

class FetchHandler(webapp2.RequestHandler):

    def get(self, year, start, end):
        end_day = calendar.monthrange(int(year),int(end))[1]
        logging.info("fetch APOD for year : %s, start : %s, end : %s, day : %s" % (year,start,end,end_day))
        start = datetime.datetime(int(year),int(start),1)
        end = datetime.datetime(int(year),int(end),end_day,23,59,59)
        logging.info("%s : %s" % (start,end))

        user = users.get_current_user()
        if user or self.request.headers['X-AppEngine-Cron']:
            fetchAPOD(self, start, end, True)
        else:
            logging.error("failed to find a user! bailing out...")

## end FetchHandler

class EmailWorker(webapp2.RequestHandler):
    def post(self):

        try:
            email = self.request.get('email')
            body = self.request.get('body')
            subject = self.request.get('subject')

            # send email
            apod_message = mail.EmailMessage()
            apod_message.subject = subject
            apod_message.sender = 'gtracy@gmail.com'
            apod_message.html = body
            apod_message.to = email
            if subject.find('APOD Email') > -1 and self.request.get('bcc') == 'True':
                apod_message.bcc = 'gtracy@gmail.com'

            apod_message.send()

        except apiproxy_errors.DeadlineExceededError:
            logging.error("DeadlineExceededError exception!?! Try to set status and return normally")
            self.response.clear()
            self.response.set_status(200)
            self.response.out.write("Task took to long for %s - BAIL!" % email)

## end EmailWorker

class BackgroundCountHandler(webapp2.RequestHandler):
    def get(self):
        self.post()

    def post(self):
        counter = 0

        q = db.GqlQuery("SELECT __key__ FROM UserSignup LIMIT 1000")
        offset = 0
        result = q.fetch(1000)
        while result:
            counter += len(result)
            offset += len(result)
            result = q.fetch(1000,offset)

        counterEntity = db.GqlQuery("SELECT * FROM UserCounter").get()
        if counterEntity is None:
            counterEntity = UserCounter()
            logging.info("we have no counter currently!? creating a new one...")
        logging.info("setting the counter to %s" % counter)
        counterEntity.userCount = counter
        counterEntity.put()
        self.response.out.write(counter)
## end


class CleanEmailsHandler(webapp2.RequestHandler):
  def get(self):
      numbers = re.compile('[0-9]')

      user_list = []
      users = db.GqlQuery("SELECT * FROM UserSignup order by date desc")
      for u in users:
          user_list.append({'key':u.key(),
                            'email':u.email,
                            'note':u.notes,
                            'referral':u.referral,
                            'date':u.date
                            })

      # add the counter to the template values
      template_values = { 'users':user_list, }

      # generate the html
      path = os.path.join(os.path.dirname(__file__), 'templates/cleaner.html')
      self.response.out.write(template.render(path, template_values))

## end MainHandler

class AdhocEmailHandler(webapp2.RequestHandler):
    def get(self):
        subject = "APOD is coming back!"
        template_file = "templates/adhocemail.html"

        # use the task infrastructure to send emails
        template_values = {  }
        path = os.path.join(os.path.dirname(__file__), template_file)
        body = template.render(path, template_values)

        # users = db.GqlQuery("SELECT email FROM UserSignup")
        # for u in users:
        #     #logging.info('Sending email to %s ' % u.email)
        #     task = Task(url='/emailqueue', params={'email':u.email,'subject':subject,'body':body})
        #     task.add('emailqueue')

        # self.response.out.write(template.render(path, template_values))

        task = Task(url='/emailqueue', params={'email':'gtracy@gmail.com','subject':'testing','body':body})
        task.add('emailqueue')
        self.response.out.write(template.render(path, template_values))

## end ApologyHandler


urlbase = "http://apod.nasa.gov/apod"
url = urlbase + "/astropix.html"
myemail = 'gtracy@gmail.com'
footerText = "<hr><p><i><strong>This is an automated email. If you notice any problems, just send me a note at <a href=mailto:gtracy@gmail.com>gtracy@gmail.com</a>. You can add and remove email addresses to this distribution list here, <a href=http://apodemail.org>http://apodemail.org</a>.</strong></i><a href='mailto:unsubscribe@apodemail-hrd.appspotemail.com?Subject=unsubscribe'>Unsubscribe</a></p>"
#googleAnalytics = "http://www.google-analytics.com/collect?v=1&tid=UA-12345678-1&cid=CLIENT_ID_NUMBER&t=event&ec=email&ea=open&el=recipient_id&cs=newsletter&cm=email&cn=Campaign_Name"

def fetchAPOD(self, start, end, sendEmail):

     logging.debug("fetching the APOD site...")

     loop = 0
     done = False
     result = None
     while not done and loop < 3:
         try:
           result = urlfetch.fetch(urlbase)
           done = True;
         except urlfetch.DownloadError:
           logging.error("Error loading page (%s)... sleeping" % loop)
           if result:
               logging.debug("Error status: %s" % result.status_code)
               logging.debug("Error header: %s" % result.headers)
               logging.debug("Error content: %s" % result.content)
           time.sleep(4)
           loop = loop+1

     if result is None or result.status_code != 200:
         logging.error("Exiting early: error fetching URL: " + result.status_code)
         return

     soup = BeautifulSoup(result.content)
     #logging.debug(soup)

     # fix all of the relative links
     for a in soup.html.body.findAll('a'):
         if a['href'].find("http") < 0:
             fullurl = "%s/%s" % (urlbase,a['href'])
             a['href'] = a['href'].replace(a['href'],fullurl)

     # fix all of the relative image source references
     for i in soup.html.body.findAll('img'):
         if i['src'].find("http") < 0:
             fullurl = "%s/%s" % (urlbase,i['src'])
             i['src'] = i['src'].replace(i['src'],fullurl)

     # soup pulled out the center tag at the end for some reason
     # so add it back in
     first, second = soup.findAll('hr')
     first.insert(0,"<center>")

     footer = Tag(soup, "p")
     footer.insert(0,footerText)
     soup('br')[-1].insert(0,footer)

     title = soup('center')[1].b.string
     subject = "APOD - %s" % title

     # template_values = { 'content':soup }
     # path = os.path.join(os.path.dirname(__file__), 'templates/cron.html')
     # self.response.out.write(template.render(path, template_values))

     user_count = 0
     if sendEmail:
         users = db.GqlQuery("SELECT email FROM UserSignup WHERE date >= :1 AND date <= :2", start, end)
         for u in users:
            user_count += 1
            task = Task(url='/emailqueue', params={'title':title,'email':u.email,'subject':subject,'body':str(soup)})
            task.add('emailqueue')

     logging.info('Spawned %s email tasks for %s' % (user_count, start))
     self.response.out.write('%s %s' % (subject, user_count))


#
# Create the WSGI application instance for the APOD signup
#
app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/dailyemail/(.*)/(.*)/(.*)', FetchHandler),
                               ('/adhocemail', AdhocEmailHandler),
                               ('/emailqueue', EmailWorker),
                               ('/usercount', BackgroundCountHandler),
                               ('/admin/clean', CleanEmailsHandler),
                              ],
                              debug=True)
