# SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
# SPDX-License-Identifier: MIT
import pypd

import bittensor as bt

def triggerPagerDutyIncident(integration_keys, source, group, event_class, msg, custom_details=None, severity="error", dedup_key=None):
    if integration_keys and len(integration_keys) > 0:
        bt.logging.error
        for integration_key in integration_keys:
            if integration_key is None: continue
            try:
                data={
                    'routing_key': integration_key,
                    'event_action': 'trigger',
                    'dedup_key' : dedup_key,
                    'payload': {
                        'summary': msg,
                        'severity': severity,
                        'source': source,
                        'class' : event_class,
                        'group' : group
                    }
                }
                if custom_details is not None:
                    data['payload']['custom_details'] = custom_details
                pypd.EventV2.create(data=data)
            except Exception as e:
                bt.logging.error(f"FAILED TO GENERATE PAGERDUTY ALERT : {str(e)}\n{data if data else ''}")

def resolvePagerDutyIncident(integration_keys, source, dedup_key):
    if integration_keys and len(integration_keys) > 0:
        for integration_key in integration_keys:
            if integration_key is None: continue
            try:
                data={
                    'routing_key': integration_key,
                    'event_action': 'resolve',
                    'dedup_key' : dedup_key,
                    'payload': {
                        "summary" : f"{source} : Incident {dedup_key} resolved.",
                        "source" : source,
                        "severity" : "info"
                    }
                }
                pypd.EventV2.create(data=data)
            except Exception as e:
                bt.logging.error(f"FAILED TO RESOLVE PAGERDUTY ALERT : {str(e)}\nDATA: {data}")           