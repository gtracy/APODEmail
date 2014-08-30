from google.appengine.ext import db

class UserSignup(db.Model):
  email = db.StringProperty()
  referral = db.StringProperty(multiline=True)
  notes = db.StringProperty(multiline=True)
  date = db.DateTimeProperty(auto_now_add=True)

class UserCounter(db.Model):
    userCount = db.IntegerProperty()

