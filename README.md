# CTFd Podman Plugin
This plugin for CTFd will allow your competing teams/users to start podmanized images for presented challenges. It adds a challenge type "podman" that can be assigned a specific podman image/tag. A few notable requirements:

* Podman Config must be set first. You can access this via `/admin/podman_config`. Currently supported config is pure http (no encryption/authentication) or full TLS with client certificate validation. Configuration information for TLS can be found here: https://docs.podman.com/engine/security/https/
* This plugin is written so that challenges are stored by tags. For example, StormCTF stores all podman challenges for InfoSeCon2019 in the `stormctf/infosecon2019` repository. A challenge example would be `stormctf/infosecon2019:arbit`. This is how you would call the challenge when creating a new challenge.


## Important Notes

* It is unknown if using the same tag twice will cause issues. This plugin was written to avoid this issue, but it has not been fully tested.
* As with all plugins, please security test your Scoreboard before launching the CTF. This plugin has been tested and vetted in the StormCTF environment, but yours may vary.
* In 2.3.3 a CTFd Configuration change is **REQUIRED**. Specifically, https://github.com/CTFd/CTFd/issues/1370. You will need to replace the function `get_configurable_plugins` with the one in the solution. This allows `config.json` to be a list, which allows multiple Menu items per plugin for the Plugins dropdown. You may want to change any other plugins you install to accommodate this. It's as simple as enclosing the curly braces with square braces. Example below.

```
# Original config.json
{
	"name": "Another Plugin",
	"route": "/admin/plugin/route"
}
```
```
# Modified config.json
[{
	"name": "Another Plugin",
	"route": "/admin/plugin/route"
}]
```
**NOTE: The above config.json modification only applies to OTHER plugins installed.**

*Requires flask_wtf*
`pip install flask_wtf`

## Features

* Allows players to create their own podman container for podman challenges.
* 5 minute revert timer.
* 2 hour stale container nuke.
* Status panel for Admins to manage podman containers currently active.
* Support for client side validation TLS podman api connections (HIGHLY RECOMMENDED).
* Podman container kill on solve.
* (Mostly) Seamless integration with CTFd.
* **Untested**: _Should_ be able to seamlessly integrate with other challenge types.

## Installation / Configuration

* Make the above required code change in CTFd 2.3.3 (`get_configurable_plugins`).
* Drop the folder `podman_challenges` into `CTFd/CTFd/plugins` (Exactly this name).
* Restart CTFd.
* Navigate to `/admin/podman_config`. Add your configuration information. Click Submit.
* Add your required repositories for this CTF. You can select multiple by holding CTRL when clicking. Click Submit.
* Click Challenges, Select `podman` for challenge type. Create a challenge as normal, but select the correct podman tag for this challenge.
* Double check the front end shows "Start Podman Instance" on the challenge.
* Confirm users are able to start/revert and access podman challenges.
* Host an awesome CTF!

### Update: 20210206
Works with 3.2.1

* Updated the entire plugin to work with the new CTFd.

#### Credits

* https://github.com/offsecginger (Twitter: @offsec_ginger)
* Jaime Geiger (For Original Plugin assistance) (Twitter: @jgeigerm)
