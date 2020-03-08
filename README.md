# Ansible collection for bamboo agent configuration
![GitHub Workflow Status](https://github.com/stefanhoelzl/ansible-bamboo-agent-collection/workflows/Build%20and%20Test/badge.svg?branch=master)

Ansible collection for bamboo remote agent configuration 
using the [REST API](https://docs.atlassian.com/atlassian-bamboo/REST/6.9.2).

## Features
- [x] [agent authentication](https://confluence.atlassian.com/bamboo/agent-authentication-289277196.html)
- [x] [enable/disable an agent](https://confluence.atlassian.com/bamboo/disabling-or-deleting-an-agent-289277174.html)
- [x] update agent name (as shown in Bamboo UI)
- [x] [dedicating an agent](https://confluence.atlassian.com/bamboo/dedicating-an-agent-629015108.html)
- [x] wait until agent is not busy
- [x] no dependencies

## Usage
checkout the repository
```bash
$ git clone git clone https://github.com/stefanhoelzl/ansible-bamboo-agent-collection.git
$ cd ansible-bamboo-agent-collection
```

build the collection
```bash
$ ./build.sh
```

install the collection
```bash
$ ansible-galaxy collection install release/stefanhoelzl.bamboo_agent-${VERSION}.tar.gz
```
for more informations how to install ansible collections see the [documentation](https://docs.ansible.com/ansible/latest/user_guide/collections_using.html#installing-collections-with-ansible-galaxy).

adding a task to your playbook
```yaml
- name: configure bamboo remote agent
  stefanhoelzl.bamboo_agent.configuration:
    host: "http://atlassian.my-domain.com/bamboo/"
    home: "/home/bamboo/bamboo-agent-home"
    name: bamboo-agent-name
    enabled: false
    assignments:
    - type: project
      key: PR
    credentials:
      user: "admin"
      password: "admin"
```

## Development
### Dependencies
The only required dependencies are `ansible` and `black` (enforces code formatting policy).
Optional can `docker-compose` be used to run the acceptance test suite.
A `Dockerfile` which specifies a development image is located in `.devcontainer`.
This can be used as a standalone container or with the [VS Code Remote Extension](https://code.visualstudio.com/docs/remote/remote-overview).

### Build
Run 
```bash 
$ ./build.sh
```
to build the collection. The built collection can be found in the `release` directory.

### Testing
Integration and unit tests can be run with
```bash
$ python tests
```

In `tests/env` is a environment with a real Bamboo server for acceptance testing defined,
using [docker compose](https://docs.docker.com/compose/).
It starts a Bamboo server, and Bamboo remote agent and an ansible control node in separate docker containers, 
runs a playbook on the ansible control node to configure the remote agent and checks if it was successfully.

The acceptance test suite can be run with 
```bash
$ tests/acceptance_tests.sh
```
