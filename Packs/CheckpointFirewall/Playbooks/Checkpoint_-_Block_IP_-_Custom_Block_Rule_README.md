This playbook blocks IP addresses using Custom Block Rules in Checkpoint Firewall.
The playbook receives malicious IP addresses as inputs, creates a custom bi-directional rule to block them, and publish the configuration.

## Dependencies
This playbook uses the following sub-playbooks, integrations, and scripts.

### Sub-playbooks
* Checkpoint - Publish&Install configuration

### Integrations
* CheckPointFirewallV2

### Scripts
* Print

### Commands
* checkpoint-logout
* checkpoint-host-add
* checkpoint-access-rule-list
* checkpoint-access-rule-add
* checkpoint-login-and-get-session-id
* checkpoint-show-objects

## Playbook Inputs
---

| **Name** | **Description** | **Default Value** | **Required** |
| --- | --- | --- | --- |
| IP | Array of malicious IPs to block. |  | Required |
| install_policy | Input True / False for playbook to continue install policy process for checkpoint Firewall. | False | Required |
| policy_package | The name of the policy package to be installed. | Standard | Required |
| block_IP_error_handling | In case one of the actions for block IP playbook fails due to issues on the Checkpoint side, This input will determine whether the playbook will continue or stop for manual review. Also, in case of Continue the session id will logout and all changes will discard.<br/>Values can be "Continue" or "Stop".<br/>The default value will be "Stop". | Stop | Optional |
| checkpoint_error_handling | In case one of the actions for publish/install policy fails due to issues on the Checkpoint side, This input will determine whether the playbook will continue or stop for manual review. Also, in case of Continue the session id will logout and all changes will discard.<br/>Values can be "Continue" or "Stop".<br/>The default value will be "Stop". | Stop | Required |
| rule_layer | This input determines whether Checkpoint firewall rule layer  are used.<br/>By default we using "Network" layer, but can be changed. | Network | Required |
| rule_position | This input determines whether Checkpoint firewall rule position  are used.<br/>By default we using "top" position, but can be changed. | top | Required |
| rule_name | This input determines whether Checkpoint firewall rule name are used. | XSOAR - ${incident.id} | Required |

## Playbook Outputs
---
There are no outputs for this playbook.

## Playbook Image
---
![Checkpoint - Block IP - Custom Block Rule](../doc_files/Checkpoint_-_Block_IP_-_Custom_Block_Rule.png)