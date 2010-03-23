from google.appengine.ext import db
from google.appengine.ext import db
from google.appengine.tools import bulkloader


class UserSignup(db.Model):
  email = db.StringProperty()
  referral = db.StringProperty()
  notes = db.StringProperty()
  date = db.DateTimeProperty(auto_now_add=True)

class EmailLoader(bulkloader.Loader):
  def __init__(self):
    bulkloader.Loader.__init__(self, 'UserSignup',
                               [('email', str),
                                ('referral', str),
                                ])

loaders = [EmailLoader]
