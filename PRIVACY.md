# CAI Trupic privacy policy for the Pinterest connection

Effective November 25, 2026

This policy covers the Pinterest connection in the account owner's local Trupic workspace. The owner uses it to view visual references from their own board. The Trupic project maintainer operates this integration for a single account.

## Information the owner provides

The workspace saves the board ID, reference-use conditions and any public feed address entered by the owner. To enable the API view, the owner supplies a read-only Pinterest access token. The local Trupic process keeps this credential in its settings or reads it from an environment variable. It sends the token to Pinterest to authenticate board requests. A public Pinterest feed can be viewed without a token.

## What happens when the owner opens a preview

Trupic requests the board or public feed from Pinterest at the owner's request. It uses Pin identifiers and titles to display links back to Pinterest. The preview is held in memory, and the response asks the browser not to cache it. Closing the preview or leaving the settings panel removes it from the view. Preview data is not written to the case library, sent to AI providers, used to train models, shared with advertisers or sold. Following a Pin link opens Pinterest, which processes that visit under its own [privacy policy](https://policy.pinterest.com/en/privacy-policy).

## Retention and removal

The owner can remove the saved token in Trupic's reference-source settings and clear the saved board ID or feed address. If the operator supplied a setting through the environment, the operator can remove that value and restart the local service. The owner can also revoke the app's authorization in Pinterest. Configuration backups are under the control of the workspace operator. Reference records created by older imports are separate from the live preview and can be identified for removal by the local workspace operator.

## Contact

To ask about the integration or request assistance with access or deletion, contact the maintainer through the [Trupic project issue tracker](https://github.com/laixi969-coder/Trupic/issues). The tracker is public. For a private matter, request a private follow-up without posting tokens, private Pin links or identifying details. The operator of the local workspace controls its data.
