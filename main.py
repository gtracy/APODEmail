import webapp2
import os
import urllib2
import re
import logging
import time

from google.appengine.api import users
from google.appengine.api import mail
from google.appengine.api import urlfetch
from google.appengine.api import quota

from google.appengine.api.labs import taskqueue
from google.appengine.api.labs.taskqueue import Task
from google.appengine.api.urlfetch import DownloadError
from google.appengine.api.mail import InvalidEmailError

from google.appengine.ext import db

from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.runtime import apiproxy_errors

from BeautifulSoup import BeautifulSoup, Tag
from django.core.validators import email_re

import config
import data_model

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

class TodayHandler(webapp2.RequestHandler):

    def get(self):
         fetchAPOD(self, False)

    def post(self):
        fetchAPOD(self, False)

## end TodayHandler


class FetchHandler(webapp2.RequestHandler):

    def get(self):

         user = users.get_current_user()
         if user or self.request.headers['X-AppEngine-Cron']:
             fetchAPOD(self, True)
         else:
             logging.error("failed to find a user! Baling out...")

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
            if subject.find('APOD Email') > -1:
                apod_message.bcc = 'gtracy@gmail.com'
            apod_message.send()
            logging.info('Sent email to %s' % apod_message.to)

            # fetch the URL to simulate a user's site visit
            try:
                result = urlfetch.fetch(urlbase)
            except urlfetch.DownloadError:
                logging.error("DownloadError while fetching the page during email delivery")
                return

        except apiproxy_errors.DeadlineExceededError:
            logging.error("DeadlineExceededError exception!?! Try to set status and return normally")
            self.response.clear()
            self.response.set_status(200)
            self.response.out.write("Task took to long for %s - BAIL!" % email)

## end EmailWorker

class APODFetchHandler(webapp2.RequestHandler):
    def post(self):
        # fetch the URL to simulate a user's site visit
        try:
            result = urlfetch.fetch(urlbase)
        except urlfetch.DownloadError:
            logging.error("APODFetchHandler :: DownloadError while fetching the APOD page")
            return

## end APODFetchHandler

class BackgroundCountHandler(webapp2.RequestHandler):
    def get(self):
        self.post()

    def post(self):
        counter = 0

        q = db.GqlQuery("SELECT * FROM UserSignup LIMIT 1000")
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

class GetEmailsHandler(webapp2.RequestHandler):
    def get(self):
        key = self.request.get('key')
        if key != config.API_SECRET:
            logging.error('ILLEGAL email request -----> key is: %s' % key)
            self.response.set_status(401)
            self.response.out.write('illegal access')
        else:
            users = db.GqlQuery("SELECT * FROM UserSignup")
            if users is None:
                self.response.out.write('empty')
            else:
                emails = ''
                for u in users:
                    emails += '%s,' % u.email

                    # here's something goofy... we're going to spawn a task
                    # to fetch the APOD site content for each user. we do
                    # this because the APOD authors ask that we maintain
                    # traffic levels on the site for users on the distribution list
                    #task = Task(url='/fetchqueue')
                    #task.add('fetchqueue')

                self.response.out.write(emails.rstrip(','))  # strip off trailing comma

## end GetEmailsHandler

class AdhocEmailHandler(webapp2.RequestHandler):
    def get(self):
        subject = "APOD is coming back!"
        template_file = "templates/adhocemail.html"

        # use the task infrastructure to send emails
        template_values = {  }
        path = os.path.join(os.path.dirname(__file__), template_file)
        body = template.render(path, template_values)

        users = data_model.UserSignup.all()
        for u in users:
            logging.info('Sending email to %s ' % u.email)
            task = Task(url='/emailqueue', params={'email':u.email,'subject':subject,'body':body})
            task.add('emailqueue')

        self.response.out.write(template.render(path, template_values))

## end ApologyHandler


urlbase = "http://apod.nasa.gov/apod"
url = urlbase + "/astropix.html"
myemail = 'gtracy@gmail.com'
footerText = "<hr><p><i><strong>This is an automated email. If you notice any problems, just send me a note at <a href=mailto:gtracy@gmail.com>gtracy@gmail.com</a>. You can add and remove email addresses to this distribution list here, <a href=http://apodemail.appspot.com>http://apodemail.appspot.com</a>.</strong></i></p>"

def fetchAPOD(self, sendEmail):

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
           time.sleep(6)
           loop = loop+1

     if result is None or result.status_code != 200:
         logging.error("Exiting early: error fetching URL: " + result.status_code)
         return

     soup = BeautifulSoup(result.content)
     logging.debug(soup)

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

     template_values = { 'content':soup }
     path = os.path.join(os.path.dirname(__file__), 'templates/cron.html')
     self.response.out.write(template.render(path, template_values))

     query_time = 0
     if sendEmail:
         users = db.GqlQuery("SELECT * FROM UserSignup")
         for u in users:
             task = Task(url='/emailqueue', params={'email':u.email,'subject':"Astronomy Picture Of The Day",'body':soup})
             task.add('emailqueue')


#
# Create the WSGI application instance for the APOD signup
#
app = webapp2.WSGIApplication([('/', MainHandler),
                                      ('/dailyemail', FetchHandler),
                                      ('/adhocemail', AdhocEmailHandler),
                                      ('/emailqueue', EmailWorker),
                                      ('/fetchqueue', APODFetchHandler),
                                      ('/usercount', BackgroundCountHandler),
                                      ('/api/emails', GetEmailsHandler),
                                      ('/pictureoftheday.*', TodayHandler),
                                      ('/admin/clean', CleanEmailsHandler),
                                      ],
                                     debug=True)
