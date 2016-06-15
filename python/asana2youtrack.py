#! /usr/bin/env python
""" Migrate your Asana workspace tasks to YouTrack.

This uses `python-asana` from https://github.com/Asana/python-asana and requires getting an Asana Personal Access Token.
For more info on getting a Personal Access Token, see https://asana.com/guide/help/api/api

Item terminology maps like so:

Asana  ...  YouTrack
-----       --------
User        User
Team        Group
Workspace   Project
Project     Subsystem
Task        Issue
Tags        Tags

This implies the following data item name mapping for each new Issue
See Asana Tasks: https://asana.com/developers/api-reference/tasks
And YouTrack Issues: https://confluence.jetbrains.com/display/YTD65/Import+Issues

Asana Task  ... YouTrack Issue
-----           --------
id              numberInProject
assignee
due_on          <None>
"""

# TODO Deal with Asana subtasks
# TODO Offer different mappings of Asana Projects to YouTrack (ie Type, Priority, Subsystem)
# TODO Add option to migrate ALL tasks or just incomplete ones
# TODO Migrate attachements

__author__ = 'Jason Haury'
import argparse
import asana
from youtrack.connection import Connection
import youtrack as yt
import json
from datetime import datetime

# ----------------------
# Global Mapping Dicts
# ----------------------
_user_map = dict()  # map by email
_workspace_map = dict()  # map by name
_project_map = dict()  # map by name
_task_map = dict()  # map by Asana name and YouTrack summary
_asana_id_map = dict()  # map Asana tasks and YouTrac issues by ID (YouTrack AsanaID field)
# These dicts refactor our API-returned lists into dicts
_a_users = dict()
_yt_users = dict()
_a_tasks = dict()
_yt_issues = dict()


# ----------------------
# Helper Functions
# ----------------------
def dump(j):
    return json.dumps(j, indent=4)


def a_to_yt_time(tstamp):
    tstamp = datetime.strptime(tstamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    return "{}{}".format(tstamp.strftime('%s'), tstamp.strftime('%f'))[:-3]


def a_to_yt_date(tstamp):
    """Asana due_on values can have a time, but generally just have a date.
    YouTrack Due Date only stores a date, not a time, so we'll slice the incoming string to only get the date.
    It must be converted to epoch time in milliseconds, even though YouTrack displays the Due Date in the same format
    as Asana stores the due_on string."""
    tstamp = datetime.strptime(tstamp[:10], '%Y-%m-%d')
    return "{}".format(int(tstamp.strftime('%s')) * 1000)


def a_id_to_yt_login(id):
    """Convert Asana user ID to corresponding YouTrack Login"""
    return _user_map[_a_users[id]['email']]['yt'].login


def get_task_details(a_conn, a_tasks):
    """ Uses locally cached JSON data if available.  Otherwise, fetches from Asana API then caches it for next time. """
    resp = []
    for task in a_tasks:
        fname = 'task_{}.json'.format(task['id'])
        try:
            with open(fname, 'r') as f:
                details = json.load(f)
        except:
            details = a_conn.tasks.find_by_id(task['id'])
            with open(fname, 'w') as f:
                json.dump(details, f)
        resp.append(details)
    return resp


def get_task_stories(a_conn, a_task):
    """ Uses locally cached JSON data if available.  Otherwise, fetches from Asana API then caches it for next time. """
    # a_stories = [a_conn.stories.find_by_id(i['id']) for i in a_conn.stories.find_by_task(a['id'])]


    fname = 'task_stories_{}.json'.format(a_task['id'])
    try:
        with open(fname, 'r') as f:
            details = json.load(f)
    except:
        details = [s for s in a_conn.stories.find_by_task(a_task['id'])]
        with open(fname, 'w') as f:
            json.dump(details, f)
    return details


def get_story_details(a_conn, a_stories):
    """ Uses locally cached JSON data if available.  Otherwise, fetches from Asana API then caches it for next time. """
    resp = []
    # [a_conn.stories.find_by_id(i['id']) for i in a_conn.stories.find_by_task(a['id'])]
    for story in a_stories:
        fname = 'story_{}'.format(story['id'])
        try:
            with open(fname, 'r') as f:
                details = json.load(f)
        except:
            details = a_conn.stories.find_by_id(story['id'])
            with open(fname, 'w') as f:
                json.dump(details, f)
        resp.append(details)
    return resp


def merge_into_map(i_list, k, map):
    """ Takes list of items (dict or obj) with some map key, `k` and the map to merge into.
    If item is a dict, it assumes it's an Asana item.  Otherwise, a YouTrack item """
    if len(i_list) == 0:
        print "ERROR: i_list is empty!"
        return
    subkey = 'a' if isinstance(i_list[0], dict) else 'yt'
    # Deal with Asana and YouTrack items differently
    if subkey == 'a':
        for i in i_list:
            if k in i and i[k] in map:
                map[i[k]][subkey] = i.copy()
            else:
                map[i[k]] = {subkey: i.copy()}
    else:
        for i in i_list:
            if not hasattr(i, k):
                continue
            if getattr(i, k) in map:
                map[getattr(i, k)][subkey] = i
            else:
                map[getattr(i, k)] = {subkey: i}


def migrate_workspace_users(a_conn, yt_conn, a_work):
    """ Migrate all users from Asana to YouTrack """
    print "Fetching Asana Users list..."
    a_users = [i for i in a_conn.users.find_by_workspace(a_work['id'])]
    print "Fetching details for {} Asana Users...".format(len(a_users))
    a_users = [a_conn.users.find_by_id(i['id']) for i in a_users]
    # Add these Asana users to our map
    merge_into_map(a_users, 'email', _user_map)
    global _a_users
    _a_users = {i['id']: i.copy() for i in a_users}
    a_emails = set([au['email'] for au in a_users])
    print "Found existing Asana Users: {} ".format(a_emails)
    yt_users = [i for i in yt_conn.getUsers()]
    print "Fetching details for {} existing YouTrack Users...".format(len(yt_users))
    yt_users = [yt_conn.getUser(i.login) for i in yt_users]
    # Add these YouTrack users to our map
    merge_into_map(yt_users, 'email', _user_map)
    global _yt_users
    _yt_users = {i.login: i for i in yt_users}

    yt_emails = set([yu.email for yu in yt_users if hasattr(yu, 'email')])
    print "Found existing YouTrack Users: {}".format(yt_emails)
    new_emails = a_emails - yt_emails
    print "Migrating these {} users to YouTrack: {}".format(len(new_emails), new_emails)
    yt_conn.importUsers(
        [dict(login=''.join(au['name'].split()), fullName=au['name'], email=au['email']) for au in new_emails if
         au['email'] in new_emails])
    return a_users, yt_users


def migrate_projects_to_subsystems(a_conn, yt_conn, a_work, yt_proj):
    """ Creates SubSystems in a YouTrack project from Projects in an Asana Workspace """
    a_work_id = a_work['id']
    # If Archived Projects are not getting picked , Tasks aren't all getting imported  because of:
    # (<error fieldName="Subsystem"....).  This is why we have  `'archived': True`
    a_projects = [p for p in a_conn.projects.find_all({'workspace': a_work_id, 'archived': True})]
    a_projects = a_projects + [p for p in a_conn.projects.find_all({'workspace': a_work_id, 'archived': False})]
    a_projects = [a_conn.projects.find_by_id(p['id']) for p in a_projects]
    merge_into_map(a_projects, 'name', _project_map)
    print "Asana {} Workspace Projects: {} ".format(a_work['name'], [p['name'] for p in a_projects])
    yt_subs = [yt_conn.getSubsystem(yt_proj.id, s.name) for s in yt_conn.getSubsystems(yt_proj.id)]
    merge_into_map(yt_subs, 'name', _project_map)
    print "YouTrack {} Project Subsystems: {}".format(yt_proj.name, [i.name for i in yt_subs])
    new_subs = set([p['name'] for p in a_projects]) - set([y.name for y in yt_subs])
    for ns in new_subs:
        # Set the Asana Project Owner to be the YouTrack Subsystem Default Assignee Login
        default_login = _user_map[_a_users[_project_map[ns]['a']['owner']['id']]['email']]['yt'].login
        print "Creating {} Subsystem: {}".format(yt_proj.name, ns)
        yt_conn.createSubsystemDetailed(yt_proj.id, ns, False, default_login)
    return a_projects, yt_subs


def migrate_tasks_to_issues(a_conn, yt_conn, a_work, yt_proj, yt_login):
    """ Asana Tasks can be in multiple Projects, yet YouTrack Issues can be in only one Subsystem.  Thus, we will
     use the 1st Project in the Asana list to use as the YouTrack Subsystem """

    # We must filter tasks by project, tag, or assignee + workspace, so we'll use the last option and migrate tasks
    # one user at a time
    numberInProject = 0
    for a_id, a_user in _a_users.iteritems():
        a_tasks = [i for i in a_conn.tasks.find_all(params={'workspace': a_work['id'], 'assignee': a_id})]
        if len(a_tasks) == 0:
            continue
        msg = "Fetching details for {} Asana Tasks assigned to {} in Workspace {}"
        print msg.format(len(a_tasks), a_user['email'], a_work['name'])
        a_tasks = get_task_details(a_conn, a_tasks)
        # print "Asana task details: {}".format(a_tasks)

        # Add to map
        merge_into_map(a_tasks, 'name', _task_map)
        global _a_tasks
        for i in a_tasks:
            _a_tasks[i['id']] = i.copy()

        print "Fetching existing YouTrack tasks"
        # Checking existing issues in YouTrack
        yt_filter = "Assignee: {}".format(_user_map[a_user['email']]['yt'].login)
        yt_issues = [i for i in yt_conn.getIssues(yt_proj.id, yt_filter, 0, 1000)]
        # yt_issues = [yt_conn.getIssue(i.id) for i in yt_conn.getIssues(yt_proj.id, yt_filter, 0, 1000)]
        merge_into_map(yt_issues, 'summary', _task_map)
        merge_into_map(yt_issues, 'AsanaID', _asana_id_map)
        global _yt_issues
        for i in yt_issues:
            _yt_issues[i.numberInProject] = i
            numberInProject = max(numberInProject, int(i.numberInProject))
        numberInProject += 1

        # print "Task details: {}".format(yt_issues)
        # Now add Issues from all Tasks
        new_issues = []
        print 'Fetching Asana stories for each task...'
        for a in a_tasks:
            # Skip adding tasks where task name matches issue summary
            if 'yt' in _task_map[a['name']] or str(a['id']) in _asana_id_map:
                print "Skipping task import : {}".format(a['name'].encode('utf-8'))
                continue

            # Look at Asana Story to find out who the YouTrack Issue reporterName should be
            a_stories = get_task_stories(a_conn, a)
            a_stories = get_story_details(a_conn, a_stories)

            # Save for later
            _a_tasks[a['id']]['stories'] = a_stories
            # Establish our comments and who created this Task
            comments = []
            reporter_name = None
            for s in a_stories:
                if s['type'] == 'comment':
                    comment = yt.Comment()
                    comment.author = a_id_to_yt_login(s['created_by']['id'])
                    # _user_map[_a_users[s['created_by']['id']]['email']]['yt'].login
                    comment.text = s['text']
                    comment.created = a_to_yt_time(s['created_at'])
                    comments.append(comment)
                elif s['type'] == 'system' and reporter_name is None and s['text'][:9] in ['assigned ', 'added to ',
                                                                                           'added sub']:
                    # TODO if subtask, link to other YT Issue
                    reporter_name = a_id_to_yt_login(s['created_by']['id'])

            # Build a list for bulk importing later
            """[{'numberInProject':'1', 'summary':'some problem', 'description':'some description', 'priority':'1',
                                    'fixedVersion':['1.0', '2.0'],
                                    'comment':[{'author':'yamaxim', 'text':'comment text', 'created':'1267030230127'}]},
                                   {'numberInProject':'2', 'summary':'some problem', 'description':'some description', 'priority':'1'}]"""

            if reporter_name is None:
                if a.get('asignee', None) is not None:
                    reporter_name = a_id_to_yt_login(a['assignee']['id'])
                else:
                    reporter_name = yt_login

            new_issue = yt.Issue()
            new_issue.comments = comments
            new_issue.reporterName = reporter_name
            new_issue['AsanaID'] = str(a['id'])
            new_issue.numberInProject = str(numberInProject)
            new_issue.summary = a.get('name', '')
            new_issue.description = a.get('notes', '')
            new_issue.state = 'Fixed' if a.get('completed', False) is True else 'Submitted'
            new_issue.assignee = a_id_to_yt_login(a['assignee']['id'])
            if a['due_on'] is not None:
                new_issue['Due Date'] = a_to_yt_date(a['due_on'])
            # new_issue = dict(numberInProject=str(a['id']), summary=a.get('name', ''), description=a.get('notes', ''),
            #                  state='Fixed' if a.get('completed', False) is True else 'Submitted')
            if 'created_at' in a:
                # created = datetime.strptime(a['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
                # created = "{}{}".format(created.strftime('%s'), created.strftime('%f'))[:-3]
                new_issue.created = a_to_yt_time(a['created_at'])
            if 'modified_at' in a:
                # updated = datetime.strptime(a['modified_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
                # updated = "{}{}".format(updated.strftime('%s'), updated.strftime('%f'))[:-3]
                # new_issue.updated = updated
                new_issue.updated = a_to_yt_time(a['modified_at'])
            if a.get('completed_at', None) is not None:
                # resolved = datetime.strptime(a['completed_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
                # resolved = "{}{}".format(resolved.strftime('%s'), resolved.strftime('%f'))[:-3]
                # new_issue.resolved = resolved
                new_issue.resolved = a_to_yt_time(a['completed_at'])
            if 'projects' in a and len(a['projects']) > 0:
                new_issue['subsystem'] = a['projects'][0]['name']

            new_issues.append(new_issue)
            numberInProject += 1
        print 'Creating new YouTrack Issues for {} (Asana IDs: {})'.format(a_user['email'],
                                                                           [n.AsanaID for n in new_issues])
        print yt_conn.importIssues(yt_proj.id, None, new_issues, test=False)

        # # only get Tasks which are not yet complete
        # now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        # global _project_map
        # for name, proj in _project_map:
        #     #a_tasks = [t for t in a_conn.tasks.find_by_project(p['id'], {'completed_since': now})]
        #     a_tasks = [t for t in a_conn.tasks.find_by_project(proj['a']['id'])]
        #     print "Found {} Asana tasks in Project {}: {}".format(len(a_tasks), p['name'], json.dumps(a_tasks, indent=4))


# ----------------------
# Main Program
# ----------------------
def main(a_pat, yt_url, yt_login, yt_pass):
    """ Creates connections to Asana and your YouTrack site, then migrates tasks """
    a_conn = asana.Client.access_token(a_pat)
    yt_conn = Connection(yt_url, yt_login, yt_pass)
    print 'Logged in with Asana User {} and YouTrack User {}'.format(a_conn.users.me()['name'],
                                                                     yt_conn.getUser(yt_login).login)

    # Get list of Asana Workspaces to migrate - all except Personal Projects
    a_workspaces = [w for w in a_conn.workspaces.find_all() if w['name'] != "Personal Projects"]
    print "Found Asana Workspaces (excluding Personal Projects): {}".format([a['name'] for a in a_workspaces])
    yt_projects = [yt_conn.getProject(p) for p in yt_conn.getProjects()]
    print "Found existing YouTrack Projects: {}".format([y.name for y in yt_projects])

    for a_work in a_workspaces:
        if a_work['name'] not in [p.name for p in yt_projects]:
            print "Creating YouTrack Project from {} Workspace".format(a_work['name'])
        yt_proj = None
        for p in yt_projects:
            if p.name == a_work['name']:
                yt_proj = p
                break
        if yt_proj is None:
            yt_proj = yt.Project()
            yt_proj.name = a_work['name']
            yt_proj.id = a_work['name'].replace(' ', '').upper()
            yt_proj.lead = yt_login
            print yt_conn.createProject(yt_proj)

        field_name = 'AsanaID'
        cf = yt.CustomField()
        cf.name = field_name
        cf.type = 'string'
        cf.isPrivate = False
        cf.visibleByDefault = False

        # print "Existing Project Fields: {}".format(yt_conn.getProjectCustomFields(yt_proj.id))
        try:
            asana_id_exists = yt_conn.getCustomField(field_name)
        except:
            asana_id_exists = False
        if not asana_id_exists:
            print 'Creating YouTrack Custom Field to save our Asana ID in'
            yt_conn.createCustomField(cf)

        try:
            asana_id_exists = yt_conn.getProjectCustomField(yt_proj.id, 'Due Date')
        except:
            asana_id_exists = None
        if not asana_id_exists:
            print 'Adding YouTrack Due Date Field to {} Project'.format(yt_proj.id)
            yt_conn.createProjectCustomFieldDetailed(yt_proj.id, 'Due Date', '')

        try:
            asana_id_exists = yt_conn.getProjectCustomField(yt_proj.id, field_name)
        except:
            asana_id_exists = False
        if not asana_id_exists:
            print 'Adding YouTrack Custom Field {} to {} Project'.format(field_name, yt_proj.id)
            yt_conn.createProjectCustomFieldDetailed(yt_proj.id, field_name, '')

        # Migrate users and save our list for later so we can assign people
        migrate_workspace_users(a_conn, yt_conn, a_work)
        migrate_projects_to_subsystems(a_conn, yt_conn, a_work, yt_proj)
        migrate_tasks_to_issues(a_conn, yt_conn, a_work, yt_proj, yt_login)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--asana_pat", '-t', help='Your Asana Personal Access Token', type=str)
    # parser.add_argument("--asana_workspace", '-w', help="Asana Workspace to migrate", type=str)
    parser.add_argument("--youtrack_url", '-u', help="YouTrack URL", type=str)
    parser.add_argument("--youtrack_login", '-l', help="YouTrack Login (user)", type=str)
    parser.add_argument("--youtrack_password", '-p', help="YouTrack Password", type=str)
    # parser.add_argument("--youtrack_project", '-r', help="YouTrack Project to migrate into", type=str)

    args = parser.parse_args()
    main(args.asana_pat, args.youtrack_url, args.youtrack_login, args.youtrack_password)
