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




TODO:
* Deal with Asana subtasks
* Create YouTrack users from Asana users
* Offer different mappings of Asana Projects to YouTrack (ie Type, Priority, Subsystem)
* Migrate all Workspaces to Projects
* Add option to migrate ALL tasks or just incomplete ones
* Migrate attachements
"""
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
_user_map = dict()
_workspace_map = dict()
_project_map = dict()
_task_map = dict()

# These dicts refactor our API-returned lists into dicts
_a_users = dict()
_yt_users = dict()


# ----------------------
# Helper Functions
# ----------------------
def dump(j):
    return json.dumps(j, indent=4)


def merge_into_map(i_list, k, map):
    """ Takes list of items (dict or obj) with some map key, `k` and the map to merge into.
    If item is a dict, it assumes it's an Asana item.  Otherwise, a YouTrack item """
    if not i_list:
        print "ERROR: i_list is empty!"
    subkey = 'a' if isinstance(i_list[0], dict) else 'yt'
    # Deal with Asana and YouTrack items differently
    if subkey == 'a':
        for i in i_list:
            if i[k] in map:
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
    _a_users = {i['id']: i for i in a_users}
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
    a_projects = [p for p in a_conn.projects.find_all({'workspace': a_work_id, 'archived': False})]
    a_projects = [a_conn.projects.find_by_id(p['id']) for p in a_projects]
    merge_into_map(a_projects, 'name', _project_map)

    print "Asana {} Workspace Projects: {} ".format(a_work['name'], dump([p for p in a_projects]))
    yt_subs = [yt_conn.getSubsystem(yt_proj.id, s.name) for s in yt_conn.getSubsystems(yt_proj.id)]
    merge_into_map(a_projects, 'name', _project_map)
    print "YouTrack {} Project Subsystems: {}".format(yt_proj.name, yt_subs)
    new_subs = set([p['name'] for p in a_projects]) - set([y.name for y in yt_subs])
    for ns in new_subs:
        # Set the Asana Project Owner to be the YouTrack Subsystem Default Assignee Login
        default_login = _user_map[_a_users[_project_map[ns]['a']['owner']['id']]['email']]['yt'].login
        print "Creating {} Subsystem: {}".format(yt_proj.name, ns)
        yt_conn.createSubsystemDetailed(yt_proj.id, ns, False, default_login)
    return a_projects, yt_subs


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
            # TODO create missing Projects from Workspaces
        for p in yt_projects:
            if p.name == a_work['name']:
                yt_proj = p
                break
        # Migrate users and save our list for later so we can assign people
        a_users, yt_users = migrate_workspace_users(a_conn, yt_conn, a_work)
        # print "YT USERS: {}".format(yt_users)

        a_projects, yt_subs = migrate_projects_to_subsystems(a_conn, yt_conn, a_work, yt_proj)
        # print "Asana projects: {}\n\n YT Subs: {}".format(a_projects, yt_subs)



        # # only get Tasks which are not yet complete
        # now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        # for p in a_projects:
        #     a_tasks = [t for t in a_conn.tasks.find_by_project(p['id'], {'completed_since': now})]
        #     print "Found Asana tasks in Project {}: {}".format(p['name'], json.dumps(a_tasks, indent=4))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--asana_pat", '-t', help='Your Asana Personal Access Token', type=str)
    parser.add_argument("--asana_workspace", '-w', help="Asana Workspace to migrate", type=str)
    parser.add_argument("--youtrack_url", '-u', help="YouTrack URL", type=str)
    parser.add_argument("--youtrack_login", '-l', help="YouTrack Login (user)", type=str)
    parser.add_argument("--youtrack_password", '-p', help="YouTrack Password", type=str)
    parser.add_argument("--youtrack_project", '-r', help="YouTrack Project to migrate into", type=str)

    args = parser.parse_args()
    main(args.asana_pat, args.youtrack_url, args.youtrack_login, args.youtrack_password)
