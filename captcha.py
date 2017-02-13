import urllib2, urllib
import json
import logging

API_SSL_SERVER="https://www.google.com/recaptcha/api"
API_SERVER="http://www.google.com/recaptcha/api"
VERIFY_SERVER="www.google.com"

class RecaptchaResponse(object):
    def __init__(self, is_valid, error_code=None):
        self.is_valid = is_valid
        self.error_code = error_code

def submit (recaptcha_response_field,
            private_key,
            remoteip):
    """
    Submits a reCAPTCHA request for verification. Returns RecaptchaResponse
    for the request

    recaptcha_response_field -- The value of recaptcha_response_field from the form
    private_key -- your reCAPTCHA private key
    remoteip -- the user's ip address
    """

    def encode_if_necessary(s):
        if isinstance(s, unicode):
            return s.encode('utf-8')
        return s

    params = urllib.urlencode ({
            'secret': encode_if_necessary(private_key),
            'remoteip' :  encode_if_necessary(remoteip),
            'response' :  encode_if_necessary(recaptcha_response_field),
            })

    request = urllib2.Request (
        url = "https://%s/recaptcha/api/siteverify" % VERIFY_SERVER,
        data = params,
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "User-agent": "reCAPTCHA Python"
            }
        )

    response = urllib2.urlopen (request)
    return_values = json.load(response)
    response.close();

    logging.info(return_values)

    if (return_values["success"] == True):
        logging.info("reCAPTCHA check : success")
        return RecaptchaResponse (is_valid=True)
    else:
        logging.error("reCAPTCHA check : fail")
        logging.error(return_values)
        return RecaptchaResponse (is_valid=False, error_code = return_values [1])
