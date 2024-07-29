# README

Installation
---

##### Provisioning a Python virtual environment
`TODO`

##### Installing `wsl`
See the docs [here](https://learn.microsoft.com/en-us/windows/wsl/install#install-wsl-command).

##### Installing `pip` dependencies
In the root of the directory, simply:
```bash
cgonzales at LAPTOP-7GN15L9T in /mnt/c/Users/cgonzales/repos/personal/az-networking on az-networking-inception [!?]
$ pip3 install -r requirements.txt
```

##### Installing the Azure CLI for logins
Find the proper executable for installating this [here](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?tabs=azure-cli#install-or-update) and then to login to run and issue commands against the Flask server, do the following:
```bash
cgonzales at LAPTOP-7GN15L9T in /mnt/c/Users/cgonzales/repos/personal/az-networking on az-networking-inception [!?]
$ az login --use-device-code
```

Biggest ticket items
---
- [ ] Swap out in memory implementation with Redis
- [ ] Integrate this with the ICM workflow
- [ ] Shipping this on AKS and having the "data download" run as a cron job?
