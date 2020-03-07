# BambooAPI

This document describes the BambooAPIs used in this module.

## Authentication

For all API calls [HTTP Basic Authentication](https://en.wikipedia.org/wiki/Basic_access_authentication) is requried.

## Access Token

To ignore the access token check for the Admin Interface add the following header `X-Atlassian-Token: no-check`.

## REST API

Detailed docuemntation about the REST API can be found [here](https://docs.atlassian.com/atlassian-bamboo/REST/latest)

* query pending agents
  * `GET /rest/api/latest/agent/authentication?pending=true`
  * expected response code: `200`
  * example response: ´[{"uuid":<agent_uuid>,"ip":"10.17.4.59","approved":false,"ipPatterns":["10.17.4.59"]}]´

* agent authentication
  * `PUT /rest/api/latest/agent/authentication/<agent_uuid>`
  * expected response code: `204`

* query agent informations
  * `GET /rest/api/latest/agent/`
  * expected response code: `200`
  * example response: ´[{"id":<agent_id>,"name":"agent-name","type":"REMOTE","active":true,"enabled":false,"busy":false}]´

* query agent assignments
  * `GET /rest/api/latest/agent/assignment?executorType=AGENT&executorId=<agent_id>`
  * expected response code: `200`
  * example response: ´[{"nameElements":["PROJECT"],"description":"","executableType":"PROJECT","id":<project_id>,"executableId":<project_id>,"executableTypeLabel":"Build project","executorType":"AGENT","executorId":<agent_id>,"capabilitiesMatch":true}]´

* add assignments
  * `POST /rest/api/latest/agent/assignment?executorType=AGENT&executorId=<agent_id>&assignmentType=PROJECT&entityId=<project_id>`
  * expected response code: `200`

* remove assignments
  * `DELETE /rest/api/latest/agent/assignment?executorType=AGENT&executorId=<project_id>&assignmentType=PROJECT&entityId=<project_id>`
  * expected response code: `204`

* list possible assignments
  * `GET /rest/api/latest/agent/assignment/search?searchTerm=&executorType=AGENT&entityType=PROJECT`
  * expected response code: `200`
  * example response: ´{"size": 1,"searchResults":[{"id":"PR","type":"PROJECT","searchEntity":{"id":<project_id>,"nameElements":["Project-Name"],"description":"Project used for testing purposes","type":"PROJECT","typeLabel":"Build project","capabilitiesMatch":true,"executorId":0}}],"start-index":0,"max-result":1}´

## Admin Interface

* update name and description
  * `POST /admin/agent/updateAgentDetails.action?agentId=<agent-id>&agentName=new-name0&agentDescription=new-description&save=Update`
  * expected response code: `302`

* disable agent
  * `POST /admin/agent/disableAgent.action?agentId=<agent_id>`
  * expected response code: `302`

* enable agent
  * `POST /admin/agent/enableAgent.action?agentId=<agent_id>`
  * expected response code: `302`

## Bamboo Agent Home

several informations can also be found in some files in the `bamboo-agent-home` directory

### `uuid-temp.properties`
This temporary file is created on agent startup and valid until the agent authentication is performed.
```
#Agent UUID stored here temporarily until the agent is approved
#Mon Mar 02 18:15:15 GMT 2020
agentUuid=<agent_uuid>
```

### `bamboo-agent.cfg.xml`
After authentication information can be retrieved from this file.
The `agentDefinition` seciont is only valid after the agent fully setup and registered on the server.
```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<configuration>
    <buildWorkingDirectory>/home/bamboo/bamboo-agent-home/xml-data/build-dir</buildWorkingDirectory>
    <agentUuid>{agent_uuid}</agentUuid>
    <agentDefinition>
        <id>{agent_id}</id>
        <name>bamboo-agent</name>
        <description>Remote agent on host bamboo-agent</description>
    </agentDefinition>
</configuration>
```
