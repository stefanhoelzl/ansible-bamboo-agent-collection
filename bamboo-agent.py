#!/usr/bin/python

# Copyright: (c) 2020, Stefan Hoelzl <stefan.hoelzl@posteo.de>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

ANSIBLE_METADATA = {
    "metadata_version": "0.1",
    "status": ["preview"],
    "supported_by": "community",
}

DOCUMENTATION = """
---
module: bamboo-agent

short_description: bamboo agent registration

version_added: "2.9.5"

description:
    - "Handles bamboo agent registraion. Allows agent assignments."

options:
    host:
        description:
            - bamboo host
        type: str
        required: true
    authentication:
        description:
            - authentication information
        required: false
        type: dict
        suboptions:
            user:
                description:
                    - Username for authentication
                type: str
                required: true
            password:
                description:
                    - Password for authentication
                type: str
                required: true
    assignments:
        description:
            - agent assignments
        required: false
        type: dict
        suboptions:
            type:
                description:
                    - assignment type
                required: true
                type: str
                choices:
                    - plan
                    - project
            id:
                description:
                    - entity id for assignment
                required: true
                type: int

author:
    - Stefan Hoelzl (@stefanhoelzl)

seealso:
    - name: Bamboo REST API documentation
      link: https://docs.atlassian.com/atlassian-bamboo/REST/
"""

EXAMPLES = """
- name: agent registration
  bamboo-agent:
    host: https://bamboo-host
"""

RETURN = ""

from ansible.module_utils.basic import AnsibleModule
import yaml


def main():
    argument_spec = yaml.load(DOCUMENTATION, Loader=yaml.SafeLoader)["options"]
    module = AnsibleModule(argument_spec=argument_spec)
    module.exit_json(changed=False)


if __name__ == "__main__":
    main()
