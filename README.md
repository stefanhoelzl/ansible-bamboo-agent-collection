# Ansible module for bamboo agent configuration

This Ansible module for bamboo remote agent configuration 
using the [REST API](https://docs.atlassian.com/atlassian-bamboo/REST/6.9.2).

## Features
[x] [agent authentication](https://confluence.atlassian.com/bamboo/agent-authentication-289277196.html)
[ ] [enable/disable an agent](https://confluence.atlassian.com/bamboo/disabling-or-deleting-an-agent-289277174.html)
[ ] update agent name (as shown in Bamboo UI)
[ ] [dedicating an agent](https://confluence.atlassian.com/bamboo/dedicating-an-agent-629015108.html)

## Usage
Add `bamboo-agent-configuration.py` to your [modules path](https://docs.ansible.com/ansible/latest/dev_guide/developing_locally.html)
or add a new path library in your `ansible.cfg` where `bamboo-agent-configuration.py` is located
```ini
[defaults]
library = /path/to/library
```

adding a task to your playbook
```yaml
- name: configure bamboo remote agent
  bamboo-agent-configuration:
    host: "http://atlassian.my-domain.com/bamboo/"
    home: "/home/bamboo/bamboo-agent-home"
    authentication: # bamboo credentials
      user: "admin"
      password: "admin"
```

## Development
### Dependencies
The only required dependencies are `ansible` and `black` (enforces code formatting policy).
A `Dockerfile` which specifies a development image is located in `.devcontainer`.
This can be used as a standalone container or with the [VS Code Remote Extension](https://code.visualstudio.com/docs/remote/remote-overview).

### Testing
Acceptance and unit tests can be run with
```bash
$ python tests
```

In `testenv` is a environment with a real Bamboo server for testing defined, using [docker compose](https://docs.docker.com/compose/).
It starts a Bamboo server, and Bamboo remote agent and an ansible control node in separate docker container, 
runs a playbook on the ansible control node to configure the remote agent and checks if it was successfully.

The test environment can be started with `./run.sh` from within the `testenv` directory. 