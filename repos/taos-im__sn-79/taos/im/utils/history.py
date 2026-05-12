# SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
# SPDX-License-Identifier: MIT
from loky.backend.context import set_start_method
set_start_method('forkserver', force=True)
from loky import get_reusable_executor, as_completed
import time
import copy

def history(snapshot, events, volume_decimals):
    history = {snapshot['timestamp']: copy.deepcopy(snapshot)}
    trades = {}
    # Apply events in chronological order
    for event in sorted(events, key=lambda x: x['t']):
        match event:
            case o if event['y'] == 'o':
                # Place new order
                if o['s'] == 0:
                    if o['p'] not in snapshot['bids']:
                        snapshot['bids'][o['p']] = {'p':o['p'], 'q':0.0, 'o':None}
                    snapshot['bids'][o['p']]['q'] = round(
                        snapshot['bids'][o['p']]['q'] + o['q'],
                        volume_decimals
                    )
                else:
                    if o['p'] not in snapshot['asks']:
                        snapshot['asks'][o['p']] =  {'p':o['p'], 'q':0.0, 'o':None}
                    snapshot['asks'][o['p']]['q'] = round(
                        snapshot['asks'][o['p']]['q'] + o['q'],
                        volume_decimals
                    )

            case t if event['y'] == 't':
                # Record trade
                trades[t['t']] = t
                if t['s'] == 0:
                    if t['p'] in snapshot['asks']:
                        snapshot['asks'][t['p']]['q'] = round(
                            snapshot['asks'][t['p']]['q'] - t['q'],
                            volume_decimals
                        )
                        if snapshot['asks'][t['p']]['q'] == 0.0:
                            del snapshot['asks'][t['p']]
                else:
                    if t['p'] in snapshot['bids']:
                        snapshot['bids'][t['p']]['q'] = round(
                            snapshot['bids'][t['p']]['q'] - t['q'],
                            volume_decimals
                        )
                        if snapshot['bids'][t['p']]['q'] == 0.0:
                            del snapshot['bids'][t['p']]

            case c if event['y'] == 'c':
                # Cancel existing order
                if c['p'] >= min(snapshot['asks'].keys()):
                    if c['p'] in snapshot['asks']:
                        snapshot['asks'][c['p']]['q'] = round(
                            snapshot['asks'][c['p']]['q'] - c['q'],
                            volume_decimals
                        )
                        if snapshot['asks'][c['p']]['q'] == 0.0:
                            del snapshot['asks'][c['p']]
                else:
                    if c['p'] in snapshot['bids']:
                        snapshot['bids'][c['p']]['q'] = round(
                            snapshot['bids'][c['p']]['q'] - c['q'],
                            volume_decimals
                        )
                        if snapshot['bids'][c['p']]['q'] == 0.0:
                            del snapshot['bids'][c['p']]

        # Add snapshot to history after each update
        snapshot['timestamp'] = event['t']
        history[event['t']] = copy.deepcopy(snapshot)
    return history, trades
    
def history_batch(snapshots, events, volume_decimals):
    start = time.time()
    result = {book_id : history(snapshot, events[book_id], volume_decimals) for book_id, snapshot in snapshots.items()}
    print(f"Calculated histories for books {list(result.keys())[0]}-{list(result.keys())[-1]} ({time.time() - start}s)")
    return result

def batch_history(snapshots, events, batches, volume_decimals):
    history_batches= []
    pool = get_reusable_executor(max_workers=len(batches))
    tasks = [pool.submit(history_batch, {book_id : snapshots[book_id] for book_id in batch}, {book_id : events[book_id] for book_id in batch}, volume_decimals) for batch in batches]
    for task in as_completed(tasks):
        result = task.result()        
        history_batches.append(result)
    return {int(k): v for d in history_batches for k, v in d.items()}