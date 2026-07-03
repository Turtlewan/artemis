# Google OAuth Setup

This provisions the owner-managed Google OAuth client used by the Artemis OAuth broker. Artemis
stores the OAuth client credentials and refresh token in the OS keychain; do not put these values in
source files or environment files.

## Create the project

Open Google Cloud Console and create a dedicated project for Artemis:

1. Go to **IAM & Admin** -> **Create a Project**.
2. Name it `Artemis Local Assistant`.
3. Select the billing organization/account you want to use, if prompted.
4. Click **Create**, then switch the console project selector to the new project.

## Configure the consent screen

Open **APIs & Services** -> **OAuth consent screen**.

1. Choose **External** user type.
2. Enter app name `Artemis`.
3. Enter your email for **User support email** and **Developer contact information**.
4. Add only the scopes Artemis needs for the Google capability you are enabling.
5. Save the consent screen.

Publish the consent screen to **Production** before using Artemis day to day.

Google OAuth apps left in **Testing** status issue refresh tokens that expire after 7 days. Production
status avoids the weekly reconnect. For a personal local app where you are the only user, this is a
status change that shows an unverified-app warning to you; it is not the Google verification review.

If you intentionally keep the app in Testing while experimenting, add your own Google account under
**Test users** and expect to reconnect Artemis every 7 days.

## Create the OAuth client

Open **APIs & Services** -> **Credentials**.

1. Click **Create Credentials** -> **OAuth client ID**.
2. Choose **Desktop app** as the application type.
3. Name it `Artemis Desktop OAuth`.
4. Click **Create**.
5. Copy the generated **Client ID** and **Client secret**.

Desktop clients use loopback redirect URIs, so no redirect URI needs to be pre-registered in the
Cloud Console.

## Store the Artemis keys

Open the Artemis keys panel and add these keychain secrets exactly:

- `google_oauth_client_id`: paste the Google OAuth **Client ID**.
- `google_oauth_client_secret`: paste the Google OAuth **Client secret**.

During the first live connect, Artemis opens a browser to Google, listens only on
`http://127.0.0.1:<port>/callback`, and stores the returned refresh token as
`google_refresh:default` in the keychain. The granted-scope record is stored as
`google_scopes:default`.

You are your own test user for this local-first app. No Google verification review is needed for
personal use, though Google may show an unverified-app warning on the consent screen.

