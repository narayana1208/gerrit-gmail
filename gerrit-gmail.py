#!/usr/bin/env python

# Copyright 2013 Joe Gordon
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Tool to mark emails of merged gerrit patches as read."""

import ConfigParser
import email
import imaplib
import json
import optparse
import subprocess
import sys

import oauth2


def run(cmd):
    print cmd
    obj = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT,
                           shell=True)
    (out, _) = obj.communicate()
    if obj.returncode != 0:
        print "The command '%s' terminated with an error." % cmd
        sys.exit(obj.returncode)
    return out


def get_review_ids(username, status):
    # TODO(jogo) un-hardcode server address
    blob = run("ssh %s@review.openstack.org -p 29418 gerrit query "
               "--format=JSON is:watched status:%s" % (username, status))
    merged_ids = []
    for line in blob.strip().split('\n'):
        review = json.loads(line)
        if "id" not in review:
            continue
        merged_ids.append(review["id"])
    return merged_ids


def connect_to_gmail(email, client_id, client_secret, refresh_token):
    access_token = None
    print "connecting to %s" % email

    if access_token is None:
        response = oauth2.RefreshToken(client_id, client_secret, refresh_token)
        access_token = response['access_token']
        # print "New Access Token: %s" % access_token
        # print "Expires in: %s" % response['expires_in']

    # before passing into IMAPLib access token needs must be converted into
    # string
    oauth2String = oauth2.GenerateOAuth2String(
        email,
        access_token,
        base64_encode=False)

    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    try:
        mail.authenticate('XOAUTH2', lambda x: oauth2String)
    except Exception:
        print "Bad access token"
        # TODO(jogo): on bad token delete cached token, use cached token
        raise
    return mail


def get_email_ids(mail, tag):
    """Return list of email_ids that can be fetched in bulk."""
    # tag where gerrit emails are stored
    mail.select(tag)
    result, data = mail.search(None, "UNSEEN")
    id_list = data[0].split()
    if len(id_list) == 0:
        print "no emails found, something is wrong"
    return ','.join(id_list)


if __name__ == "__main__":
    configparser = ConfigParser.ConfigParser()
    configparser.read('gerrit-gmail.conf')

    optparser = optparse.OptionParser()
    optparser.add_option('-r', '--read', action='store_true',
                         help='mark emails as read')
    optparser.add_option('-a', '--abandoned', action='store_true',
                         help='get abandoned patches, instead of merged')
    options, args = optparser.parse_args()

    status = 'merged'
    if options.abandoned:
        status = 'abandoned'
    merged_ids = get_review_ids(configparser.get("gerrit", "username"),
                                status=status)
    mail = connect_to_gmail(
        configparser.get("gmail", "email"),
        configparser.get("gmail", "client_id"),
        configparser.get("gmail", "client_secret"),
        configparser.get("gmail", "refresh_token"))

    # List closed so don't display multiple times
    closed = set()
    print "Closed patches:"
    tag = configparser.get("gmail", "tag")
    result, data = mail.fetch(get_email_ids(mail, tag),
                              "(BODY.PEEK[HEADER])")
    for blob in data:
        if len(blob) < 2:
            # TODO(jogo) handle edge cases better
            # this catches random parenthesis
            continue
        message = email.message_from_string(blob[1])
        change_id = message['X-Gerrit-Change-Id']
        if change_id in merged_ids:
            if options.read:
                email_id = blob[0].split()[0]
                mail.fetch(email_id, "(RFC822)")  # mark as read
            if change_id not in closed:
                closed.add(change_id)
                print "%s: '%s'" % (message['X-Gerrit-ChangeURL'],
                                    message['Subject'].replace('\r\n', ''))
    print "total: %s" % len(closed)
