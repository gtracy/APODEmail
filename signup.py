import webapp2
import os
import urllib2
import re
import logging
import time

from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.api import quota
from google.appengine.api import mail

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
import captcha


class SignupHandler(webapp2.RequestHandler):
    def post(self):
        logging.info("New signup request...\n\tEmail: %s\n\tAdd/Remove: %s\n\tReference: %s\n\tNotes: %s",
                     self.request.get('string'), self.request.get('signup'), self.request.get('reference'), self.request.get('comments'))

        # first validate the email address
        if not email_re.search(self.request.get('string')):
            error_msg = "This address - %s - is not a valid email address. Check the formatting." % self.request.get('string')
            logging.error(error_msg)
            self.response.out.write("Oops. The email address was malformed! Please try again.")
            return

        message = mail.EmailMessage(sender="APOD Email <gtracy@gmail.com>")

        blocked = False
        # determine if this is a signup or remove request
        if self.request.get('signup') == 'signup':

            # first validate the captcha
            challenge = self.request.get('recaptcha_challenge_field')
            response  = self.request.get('recaptcha_response_field')
            remoteip  = self.request.get('remote_addr')
            logging.info("Captcha request... \n\tchallenge: %s\n\tresponse: %s\n\tIP: %s\n\t",
                challenge,response,remoteip)
            cResponse = captcha.submit(
                challenge,
                response,
                config.RECAPTCHA_PRIVATE_KEY,
                remoteip)
            if cResponse.is_valid:
                logging.debug('Captcha Success!')
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
                userSignup = data_model.UserSignup()
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
                    path = os.path.join(os.path.dirname(__file__), 'templates/invalid-email.html')
                    message.html = template.render(path,template_values)

                    # setup the confirmation page on the web
                    #path = os.path.join(os.path.dirname(__file__), 'templates/invalid.html')
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
                    path = os.path.join(os.path.dirname(__file__), 'templates/added-email.html')
                    message.html = template.render(path,template_values)

                    # setup the confirmation page on the web
                    #path = os.path.join(os.path.dirname(__file__), 'templates/added.html')
                    msg = "<h2>Excellent! You've been added to the list.</h2><p class='lead'>Please consider a donation to support this project.</p>"
            else:
                blocked = True
                msg = cResponse.error_code
                logging.error('Captcha Fail %s ' % msg)

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
                path = os.path.join(os.path.dirname(__file__), 'templates/removed-email.html')
                message.html = template.render(path,template_values)

                # ... and show the thank you confirmation page
                msg = "<h2>You've been removed from the list... Thanks!</h2>"
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

class DeleteUserHandler(webapp2.RequestHandler):
    def post(self):
        user_key = self.request.get("user_key")
        user = db.get(user_key)
        if user is None:
            logging.error('trying to delete user ID %s and FAILED' % user_key)
        else:
            logging.debug('trying to delete user %s and SUCCEEDED' % user_key)
            user.delete()
## end


#
# Create the WSGI application instance for the APOD signup
#
app = webapp2.WSGIApplication([('/signup', SignupHandler),
                               ('/admin/delete/user', DeleteUserHandler)
                              ], debug=True)


