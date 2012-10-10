# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.
import time, hashlib, os
from twisted.internet import defer

class UnauthorizedError(Exception):
    """
    The given key wasn't acceptable for the requested operation.
    """


def postgres_probably_connect(name, username):
    """
    Connect to postgres or die trying.
    """
    try:
        import pgdb
    except ImportError:
        try:
            import psycopg2
        except ImportError:
            from pg8000 import pg8000_dbapi
            module = pg8000_dbapi
            con = pg8000_dbapi.connect(username, host='localhost', database=name)
        else:
            module = psycopg2
            con = psycopg2.connect(host="/var/run/postgresql", database=name,  user=username)
    else:
        module = pgdb
        con = pgdb.connect(host="127.0.0.1", database=name, user=username)
    return module, con


def sqlite_connect(path):
    import sqlite3
    return sqlite3, sqlite3.connect(path)


class DBStore(object):
    """
    Abstract access to Trac's SQL database.

    @param connection: A Python DB-API database connection.
    """
    def __init__(self, connection):
        module, self.connection = connection
        if module.paramstyle == 'qmark':
            self.pl = '?'
        else:
            self.pl = '%s'

    def q(self, query):
        """
        Replace ? in SQL strings with the db driver's placeholder.
        """
        return query.replace('?', self.pl)

    def fetchTicket(self, ticketNumber):
        """
        Look up a ticket and its concomitant changes and attachments.
        """
        c = self.connection.cursor()
        c.execute(self.q(
                "SELECT id, type, time, changetime, component, priority, owner,"
                " reporter, cc, status, resolution, summary, description, "
                "keywords FROM ticket WHERE id = ?"), [ticketNumber])
        ticketRow = c.fetchone()
        c.execute(self.q("SELECT time, author, field, oldvalue, newvalue "
                         "FROM ticket_change WHERE ticket = ? ORDER BY time"),
                  [ticketNumber])
        changeFields = ['time', 'author', 'field', 'oldvalue', 'newvalue']
        ticketFields = ["id", "type", "time", "changetime", "component", "priority", "owner",
                        "reporter", "cc", "status", "resolution", "summary",
                        "description", "keywords"]
        changesRow = c.fetchall()
        ticket = dict([(k, v or '') for k, v in zip(ticketFields, ticketRow)])

        c.execute(self.q("SELECT name, value from ticket_custom where name "
                         "in ('branch', 'branch_author', 'launchpad_bug') "
                         "and ticket = ?"),
                  [ticketNumber])
        ticket.update(c.fetchall())
        ticket['attachments'] = []
        ticket['changes'] = []
        for change in changesRow:
            ticket['changes'].append(dict([(k, v or '') for k, v in zip(changeFields, change)]))
        return defer.succeed(ticket)


    def lookupByEmail(self, email):
        """
        Find a username by looking up the associated email address.
        """
        c = self.connection.cursor()
        c.execute(self.q("SELECT sid from session_attribute "
                         "where name = 'email' and authenticated = 1 "
                                               "and value = ?"), (email,))
        result = c.fetchall()
        if not result:
            username = email
            c.execute(self.q("DELETE FROM session where sid = ?"), (email,))
            c.execute(
                self.q("INSERT INTO session (sid, authenticated, last_visit) "
                       "VALUES (?, ?, ?)"), (email, 1, time.time()))
            c.execute(self.q("INSERT INTO session_attribute "
                             "(sid, authenticated, name, value) "
                             "VALUES (?, ?,'email', ?)"),
                      (email, 1, email))
            self.connection.commit()
        else:
            username = result[0][0]
        c.execute(self.q("SELECT cookie from auth_cookie where name = ?"),
                  (username,))
        result = c.fetchall()
        if not result:
            key = hashlib.sha1(os.urandom(16)).hexdigest()
            c.execute(self.q("INSERT INTO auth_cookie VALUES (?, ?, '', ?)"),
                      (key, username, int(time.time())))
            self.connection.commit()
        else:
            key = result[0][0]
        return defer.succeed((key, username))


    def _auth(self, key):
        c = self.connection.cursor()
        c.execute(self.q("SELECT name from auth_cookie where cookie = ?"),
                  (key,))
        data = c.fetchall()
        if not data:
            return None
        else:
            return data[0][0]

    def updateTicket(self, key, id, data):
        """
        Change a ticket's fields and add to its change log.
        """
        customfields =  ('branch', 'branch_author', 'launchpad_bug')
        fields = ('type', 'component', 'priority', 'owner', 'reporter',
                  'cc', 'status', 'resolution', 'summary', 'description',
                  'keywords')
        comment = data.get('comment')
        customdata = dict((k, v) for (k, v) in data.iteritems()
                          if k in customfields
                             and v is not None)
        data = dict((k, v) for (k, v) in data.iteritems() if k in fields
                                                             and v is not None)
        username = self._auth(key)
        if not username:
            return defer.fail(UnauthorizedError())
        try:
            c = self.connection.cursor()
            c.execute(self.q("SELECT %s from ticket where id = ?"
                             % (','.join(data.keys()),)),
                      (id,))
            oldversion = dict(zip(data.keys(), c.fetchone()))
            c.execute(self.q("SELECT name, value from ticket_custom where ticket = ?"),
                      (id,))
            bits = c.fetchall()
            oldversion.update(dict.fromkeys(customfields, ''))
            oldversion.update(bits)
            t = time.time()
            c.execute(self.q("UPDATE ticket SET %s, changetime=? WHERE id = ?"
                             % ','.join(k + "=?" for k in data)),
                      data.values() + [t, id])
            changes = data.copy()
            changes.update(customdata)
            for k in changes:
                if oldversion[k] != changes[k]:
                    c.execute(self.q("""INSERT INTO ticket_change
                                   (ticket, time, author, field, oldvalue, newvalue)
                                   VALUES (?, ?, ?, ?, ?, ?)"""),
                              [id, t, username, k, oldversion[k], changes[k]])

            for k in customdata:
                if customdata[k] != oldversion[k]:
                    c.execute(self.q("""UPDATE ticket_custom SET value=?
                                    WHERE ticket=? and name=?"""),
                              (customdata[k], id, k))
                    c.execute(self.q("""INSERT INTO ticket_custom
                                    (value, ticket, name)
                                    SELECT ?, ?, ? WHERE NOT EXISTS
                                   (SELECT 1 FROM ticket_custom WHERE ticket=?
                                                                AND name=?)"""),
                              (customdata[k], id, k, id, k))

            c.execute(self.q("""SELECT max(CAST (oldvalue AS float))
                                    from ticket_change where ticket=?
                                                         and field='comment'
                                                         and oldvalue != ''"""),
                      (id,))
            lastcommentnum = int(c.fetchone()[0])
            c.execute(self.q("""INSERT INTO ticket_change
                                (ticket, time, author, field, oldvalue, newvalue)
                                VALUES (?, ?, ?, 'comment', ?, ?)"""),
                      [id, t, username, lastcommentnum, comment or ''])
            self.connection.commit()
        except:
            self.connection.rollback()
            raise
        return defer.succeed(None)
