import cgi
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

from google.appengine.ext import webapp
from google.appengine.ext import db

from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.runtime import apiproxy_errors

from BeautifulSoup import BeautifulSoup, Tag
from django.core.validators import email_re

class UserSignup(db.Model):
  email = db.StringProperty()
  referral = db.StringProperty(multiline=True)
  notes = db.StringProperty(multiline=True)
  date = db.DateTimeProperty(auto_now_add=True)

class UserCounter(db.Model):
    userCount = db.IntegerProperty()
    
    
class MainHandler(webapp.RequestHandler):
  def get(self):
      
      # figure out how many people are currently on the distribution list
      counter = db.GqlQuery("SELECT * FROM UserCounter").get()
            
      # add the counter to the template values
      template_values = { 'counter':counter.userCount, }
      
      # generate the html
      path = os.path.join(os.path.dirname(__file__), 'index.html')
      self.response.out.write(template.render(path, template_values))

## end MainHandler
        
class SignupHandler(webapp.RequestHandler):
    def post(self):
        logging.info("New signup request...\n\tEmail: %s\n\tAdd/Remove: %s\n\tReference: %s\n\tNotes: %s",
                     self.request.get('string'), self.request.get('signup'), self.request.get('reference'), self.request.get('comments'))

        # send email to the new user
        message = mail.EmailMessage()
        message.sender='gtracy@gmail.com'

        # first validate the email address
        logging.debug("Checking to see if %s is valid" % self.request.get('string'))
        if not email_re.search(self.request.get('string')):
            error_msg = "This address - %s - is not a valid email address. Check the formatting." % self.request.get('string')
            logging.error(error_msg)
            self.response.out.write("Oops. The email address was malformed! Please try again.")
            return
                
        blocked = False        
        # determine if this is a signup or remove request
        if self.request.get('signup') == 'signup':
            email_addr = self.request.get('string').lower()

            # first check to see if the user is already on the list
            q = db.GqlQuery("SELECT * FROM UserSignup WHERE email = :1", email_addr)
            remove_entry = q.fetch(1)
            if len(remove_entry) > 0:
              error_msg = "This address - %s - is already on the distribution list." % email_addr
              logging.error(error_msg)
              self.response.out.write("Oops. It looks like this email address is already on the list.")
              return
            
            # if signing up, create a new user and add it to the store
            userSignup = UserSignup()
            userSignup.email = email_addr
            userSignup.referral = self.request.get('reference')
            userSignup.notes = self.request.get('comments')
            
            # filter out requests if there is a URL in the comments field
            if re.search("http",userSignup.referral) or re.search("http",userSignup.notes):
                error_msg = "Request to add - %s - has been BLOCKED because of illegal text in the comments field." % email_addr
                logging.error(error_msg)
                template_values = {'error':error_msg}

                # setup the specific email parameters                        
                message.subject="APOD Email Signup BLOCKED"
                message.to = email_addr
                path = os.path.join(os.path.dirname(__file__), 'invalid-email.html')
                message.html = template.render(path,template_values)

                # setup the confirmation page on the web                
                #path = os.path.join(os.path.dirname(__file__), 'invalid.html')
                msg = "Oops. No can do. This request is getting blocked because it looks fishy."                
            else:
                # add the user to the database!                
                userSignup.put()

                template_values = {'email':userSignup.email, 
                                   'referral':userSignup.referral,
                                   'notes':userSignup.notes,
                                   }

                # setup the specific email parameters                        
                message.subject="APOD Email Signup Confirmation"
                message.to = email_addr
                path = os.path.join(os.path.dirname(__file__), 'added-email.html')
                message.html = template.render(path,template_values)

                # setup the confirmation page on the web
                #path = os.path.join(os.path.dirname(__file__), 'added.html')
                msg = "Excellent! You've been added to the list.<p>Please consider a donation to support this project."
            
        else:
            email_addr = self.request.get('string').lower()
            # if removing a user, first check to see that the request is valid
            q = db.GqlQuery("SELECT * FROM UserSignup WHERE email = :1", email_addr)
            remove_entry = q.fetch(1)
            if len(remove_entry) > 0:
                # if the user was found, remove them
                db.delete(remove_entry)

                # setup the specific email parameters                        
                message.subject="APOD Email Removal Request"
                message.to = self.request.get('string')
                template_values = { 'email':email_addr, 
                                    'referral':self.request.get('reference'),
                                    'notes':self.request.get('comments'),
                                 }
                path = os.path.join(os.path.dirname(__file__), 'removed-email.html')
                message.html = template.render(path,template_values)
    
                # ... and show the thank you confirmation page
                msg = "You've been removed from the list... Thanks!"
            else:
                error_msg = "This address - %s - is not on the distribution list!?" % email_addr
                logging.error(error_msg)
                msg = "Oops. This address doesn't appear to be on the list."
                blocked = True

        # send the message off...
        if not blocked:
            logging.debug("Sending email!")
            task = Task(url='/emailqueue', params={'email':message.to,'subject':message.subject,'body':message.html})
            task.add('emailqueue')

        # report back on the status
        logging.debug(msg)
        self.response.out.write(msg)

    def get(self):
        self.post()
        
## end SignupHandler

class TodayHandler(webapp.RequestHandler):
    
    def get(self):
         fetchAPOD(self, False)

    def post(self):
        fetchAPOD(self, False)
        
## end TodayHandler

        
class FetchHandler(webapp.RequestHandler):
    
    def get(self):

         user = users.get_current_user()
         logging.debug("started FetchHandler with user, %s", user)
         logging.debug("header: %s", self.request.headers)
         if user or self.request.headers['X-AppEngine-Cron']:
             fetchAPOD(self, True)
         else:
             logging.error("failed to find a user! Baling out...")

## end FetchHandler
         
class EmailWorker(webapp.RequestHandler):
    def post(self):
        
        try:
            email = self.request.get('email')
            body = self.request.get('body')
            subject = self.request.get('subject')
            logging.debug("email task running for %s", email)
        
            # send email 
            apod_message = mail.EmailMessage()
            apod_message.subject = subject
            apod_message.sender = 'apod@gregtracy.com'
            apod_message.html = body
            apod_message.to = email
            if subject.find('APOD Email') > -1:
                apod_message.bcc = 'gtracy@gmail.com'
            apod_message.send()
            logging.info('regardless of what happens next, this message was sent!')

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

class BackgroundCountHandler(webapp.RequestHandler):
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

    
urlbase = "http://apod.nasa.gov/apod"
url = urlbase + "/astropix.html"
myemail = 'gtracy@cs.wisc.edu'
footerText = "<hr><p><i><strong>This is an automated email. If you notice any problems, just send me a note at <a href=mailto:gtracy@cs.wisc.edu>gtracy@cs.wisc.edu</a>. You can add and remove email addresses to this distribution list here, <a href=http://apodemail.appspot.com>http://apodemail.appspot.com</a>.</strong></i></p>"

def fetchAPOD(self, sendEmail):
    
     logging.debug("fetching the APOD site...")
     start = quota.get_request_cpu_usage()

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
           
     fetch_time = quota.get_request_cpu_usage()
     logging.info("fetching the URL cost %d cycles" % (fetch_time-start))
        
     if result is None or result.status_code != 200:
         logging.error("Exiting early: error fetching URL: " + result.status_code)
         return 
     
     soup = BeautifulSoup(result.content)
     
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

     parse_time = quota.get_request_cpu_usage()
     logging.debug("parsing the HTML cost %d cycles" % (parse_time - fetch_time))
         
     template_values = { 'content':soup }
     path = os.path.join(os.path.dirname(__file__), 'cron.html')
     self.response.out.write(template.render(path, template_values))

     template_time = quota.get_request_cpu_usage()
     logging.debug("creating the template cost %d cycles" % (template_time - parse_time))
     query_time = 0
     if sendEmail:
         users = db.GqlQuery("SELECT * FROM UserSignup")
         query_time = quota.get_request_cpu_usage()
         logging.debug("email query cost %d cycles" % (query_time - template_time))
         for u in users:
             task = Task(url='/emailqueue', params={'email':u.email,'subject':"Astronomy Picture Of The Day",'body':soup})
             task.add('emailqueue')

     task_time = quota.get_request_cpu_usage()
     logging.debug("adding tasks cost %d cycles" % (task_time - query_time))

            
#
# Create the WSGI application instance for the APOD signup
#
application = webapp.WSGIApplication([('/', MainHandler),
                                      ('/signup', SignupHandler),
                                      ('/dailyemail', FetchHandler),
                                      ('/emailqueue', EmailWorker),
                                      ('/usercount', BackgroundCountHandler),
                                      ('/pictureoftheday.*', TodayHandler),
                                      ],
                                     debug=True)

def main():
  logging.getLogger().setLevel(logging.INFO)
  run_wsgi_app(application)

if __name__ == '__main__':
  main()
