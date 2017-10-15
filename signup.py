import webapp2
import os
import re
import logging

from google.appengine.api import mail
from google.appengine.api.labs.taskqueue import Task
from google.appengine.ext import db
from google.appengine.ext.webapp import template

from google.appengine.ext.webapp.mail_handlers import BounceNotificationHandler
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler


from django.core.validators import email_re

import config
import data_model
import captcha


class SignupHandler(webapp2.RequestHandler):
    def post(self):
        logging.info("New signup request...\n\tEmail: %s\n\tAdd/Remove: %s\n\tReference: %s\n\tNotes: %s",
                     self.request.get('string'), self.request.get('signup'), self.request.get('reference'), self.request.get('comments'))

        # first validate the email address
        email_addr = self.request.get('string').lower().strip()
        if not email_re.match(email_addr):
            error_msg = "This address - %s - is not a valid email address. Check the formatting." % email_addr
            logging.error(error_msg)
            self.response.out.write("Oops. The email address was malformed! Please try again.")
            return

        message = mail.EmailMessage(sender="APOD Email <gtracy@gmail.com>")

        blocked = False
        bcc = False
        # determine if this is a signup or remove request
        if self.request.get('signup') == 'signup':

            # first validate the captcha
            response  = self.request.get('g-recaptcha-response')
            remoteip  = self.request.get('remote_addr')
            logging.info("Captcha request... \n\tresponse: %s\n\tIP: %s\n\t",response,remoteip)
            cResponse = captcha.submit(
                response,
                config.RECAPTCHA_PRIVATE_KEY,
                remoteip)
            if cResponse.is_valid:
                logging.debug('Captcha Success!')

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

            # send the SIGNUP message off...
            if not blocked:
                logging.debug("Sending email!")
                task = Task(url='/emailqueue', params={'email':message.to,'subject':message.subject,'body':message.html,'bcc':bcc})
                task.add('emailqueue')

        else:
            msg = unsubscribe(email_addr,self.request.get('comments'))

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

class LogBounceHandler(BounceNotificationHandler):
    def receive(self, bounce_message):
        logging.info('Received bounce post ... [%s]', self.request)
        logging.info('Bounce original: %s', bounce_message.original)
        logging.info('Bounce notification: %s', bounce_message.notification)
        #unsubsribe()

## end bounce handler

class UnsubscribeHandler(InboundMailHandler):
    def receive(self, mail_message):
        sender_string = mail_message.sender.lower()
        sender_email = sender_string
        if "<" in sender_string and ">" in sender_string:
            sender_email = sender_string.split('<')[1].split('>')[0]

        logging.info("Received a message from: " + sender_email)
        logging.info("Subject: " + mail_message.subject.lower())

        if mail_message.subject.lower() == "unsubscribe":
            logging.info("Unsubscribing " + sender_email + " via email ")
            unsubscribe(sender_email,'email unsubscribe')
        else:
            logging.info("Invalid subject. Do nothing for, " + mail_message.subject)
            
## end unsubscribe handler

def unsubscribe(email,notes):
    blocked = False
    bcc = False
    message = mail.EmailMessage(sender="APOD Email <gtracy@gmail.com>")

    email_addr = email.lower()
    q = db.GqlQuery("SELECT * FROM UserSignup WHERE email = :1", email_addr)
    remove_entry = q.fetch(1)
    if len(remove_entry) > 0:
        # if the user was found, remove them
        db.delete(remove_entry)

        # setup the specific email parameters
        message.subject="APOD Email Removal Request"
        message.to = email_addr
        template_values = {'email':email_addr,'notes':notes}
        path = os.path.join(os.path.dirname(__file__), 'templates/removed-email.html')
        message.html = template.render(path,template_values)

        # ... and show the thank you confirmation page
        msg = "<h2>You've been removed from the list... Thanks!</h2>"

        # email me if they've left comments
        if notes and len(notes) > 0:
            bcc = True
    else:
        error_msg = "This address - %s - is not on the distribution list!?" % email_addr
        logging.error(error_msg)
        msg = "Oops. This address doesn't appear to be on the list."
        blocked = True

    # send the message off...
    if not blocked:
        logging.debug("Sending email!")
        task = Task(url='/emailqueue', params={'email':message.to,'subject':message.subject,'body':message.html,'bcc':bcc})
        task.add('emailqueue')

    return msg

## end unsubscribe


#
# Create the WSGI application instance for the APOD signup
#
app = webapp2.WSGIApplication([('/signup', SignupHandler),
                               ('/admin/delete/user', DeleteUserHandler),
                               (LogBounceHandler.mapping()),
                               (UnsubscribeHandler.mapping())
                              ], debug=True)


