"""One-time connection: exchange an OAuth code for tokens and store them encrypted.

Usage (run by .github/workflows/connect.yml): python scripts/connect.py strava|whoop CODE
Never print tokens: the Action logs of a public repository are public.
"""
import sys, time
sys.path.insert(0, __import__('os').path.dirname(__file__))
import os
from sync import http, load_tokens, save_tokens

REDIRECT = 'https://zbyan123-bit.github.io/ftp-dashboard/callback.html'


def main():
    service, code = sys.argv[1].strip().lower(), sys.argv[2].strip()
    tok = load_tokens()
    if service == 'strava':
        r = http('POST', 'https://www.strava.com/oauth/token', {
            'client_id': os.environ['STRAVA_CLIENT_ID'], 'client_secret': os.environ['STRAVA_CLIENT_SECRET'],
            'code': code, 'grant_type': 'authorization_code'})
        tok['strava'] = {k: r[k] for k in ('access_token', 'refresh_token', 'expires_at')}
        who = (r.get('athlete') or {}).get('firstname', '')
        print(f'Strava connected{" for " + who if who else ""}. Scope check: make sure you ticked "View data about your private activities".')
    elif service == 'whoop':
        r = http('POST', 'https://api.prod.whoop.com/oauth/oauth2/token', {
            'client_id': os.environ['WHOOP_CLIENT_ID'], 'client_secret': os.environ['WHOOP_CLIENT_SECRET'],
            'code': code, 'grant_type': 'authorization_code', 'redirect_uri': REDIRECT})
        if not r.get('refresh_token'):
            sys.exit('WHOOP gave no refresh token: the authorise link must include the "offline" scope')
        tok['whoop'] = {'access_token': r['access_token'], 'refresh_token': r['refresh_token'],
                        'expires_at': int(time.time()) + int(r.get('expires_in', 3600))}
        print('WHOOP connected.')
    else:
        sys.exit('service must be strava or whoop')
    save_tokens(tok)


if __name__ == '__main__':
    main()
