# import os
# from authlib.integrations.starlette_client import OAuth

# oauth = OAuth()

# oauth.register(
#     name='google',
#     client_id=os.getenv('GOOGLE_CLIENT_ID'),
#     client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
#     authorize_url='https://accounts.google.com/o/oauth2/auth',
#     authorize_params=None,
#     access_token_url='https://accounts.google.com/o/oauth2/token',
#     access_token_params=None,
#     refresh_token_url=None,
#     redirect_uri=os.getenv('GOOGLE_REDIRECT_URI'),
#     client_kwargs={'scope': 'openid email profile'},
# )
