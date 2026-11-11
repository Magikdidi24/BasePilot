'''Is a newer BasePilot released? One unauthenticated request at launch to the GitHub API
for the latest release of this project (pre-releases are not "latest"). Nothing about the
user is sent: the request carries only the app's name and version as User-Agent, which
GitHub asks of every client. Off with *Settings → Check for a new version at launch*.
'''
import json
import re
import urllib.request

from app.utils.logger import setup_logger

logger = setup_logger('UpdateCheck')

RELEASES_API = 'https://api.github.com/repos/Magikdidi24/BasePilot/releases/latest'
RELEASES_PAGE = 'https://github.com/Magikdidi24/BasePilot/releases/latest'


def parse_version(text):
    '''(1, 0, 2) from "v1.0.2"; a pre-release suffix ("-beta.2") is left out. None when
    the text holds no version.'''
    match = re.match(r'\s*v?(\d+(?:\.\d+)*)', str(text or ''))
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split('.')]
    while len(parts) > 1 and parts[-1] == 0:  # 1.0 == 1.0.0
        parts.pop()
    return tuple(parts)


def is_newer(latest, current):
    '''``latest`` (a release tag) is a later version than ``current``.'''
    (a, b) = (parse_version(latest), parse_version(current))
    return a is not None and b is not None and a > b


def latest_release(version, timeout = 5.0, opener = urllib.request.urlopen):
    '''``(tag, page url)`` of the latest release, or None when it cannot be told (offline,
    rate-limited...): never raises.'''
    request = urllib.request.Request(RELEASES_API, headers = {'User-Agent': f'BasePilot/{version}', 'Accept': 'application/vnd.github+json'})
    try:
        with opener(request, timeout = timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        logger.info('Update check skipped: %s', exc)
        return None
    tag = data.get('tag_name') if isinstance(data, dict) else None
    if not tag:
        return None
    return (str(tag), str(data.get('html_url') or RELEASES_PAGE))


def newer_release(version, **kwargs):
    '''``(tag, url)`` when the latest release is newer than ``version``, else None.'''
    found = latest_release(version, **kwargs)
    return found if found and is_newer(found[0], version) else None
