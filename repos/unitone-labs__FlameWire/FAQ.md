# Bittensor Node - FlameWire  – Troubleshooting FAQ

---

## 1. `rpc/sync failed`

**Cause**  
Your RPC endpoint is either offline or still catching up with the Bittensor network.

**How to fix**

1. **Check if the RPC is online**  
   ```bash
   curl -X POST http://<RPC_URL>         -H 'Content-Type: application/json'         -d '{"jsonrpc":"2.0","method":"system_health","params":[],"id":1}'
   ```  
   - `isSyncing: false` → node is fully synced.  
   - No response or connection error → RPC not reachable.

2. **Inspect node logs**  
   ```bash
   docker logs <container_name> | tail -n 50
   ```  
   Look for `Idle` (synced) or `Syncing`.

3. **Verify the port is open**  
   ```bash
   nc -vz <NODE_IP> 9944
   ```

4. **Wait or restart**  
   If syncing stalls, restart the node:  
   ```bash
   docker restart <container_name>
   ```

---

## 2. `failed listen addr: ...`

**Cause**  
The RPC call `system_localListenAddresses` returns no data or times out.

**How to fix**

1. Call the method manually:
   ```bash
   curl -X POST http://<RPC_URL>         -H 'Content-Type: application/json'         -d '{"jsonrpc":"2.0","method":"system_localListenAddresses","params":[],"id":1}'
   ```
2. If the result is empty or `null`, ensure the node was launched with correct flags, e.g.  
   `--listen-addr /ip4/0.0.0.0/tcp/30333`
3. Examine logs for RPC or network errors and open the firewall port.

---

## 3. `invalid listen addr resp: ...`

**Cause**  
The response from `system_localListenAddresses` is malformed JSON or unexpected.

**How to fix**

1. Re‑run the call (see #2) and verify it returns valid JSON with a `result` field.  
2. Check the node version:
   ```bash
   curl -X POST http://<RPC_URL>         -H 'Content-Type: application/json'         -d '{"jsonrpc":"2.0","method":"system_version","params":[],"id":1}'
   ```
3. Upgrade to the latest Bittensor release and restart.

---

## 4. `no addresses in response`

**Cause**  
The node returns an empty array for listen addresses.

**How to fix**

1. Launch the node with explicit public binding:  
   ```
   --listen-addr /ip4/0.0.0.0/tcp/30333    --public-addr /ip4/<PUBLIC_IP>/tcp/30333
   ```
2. Confirm firewall/NAT rules allow inbound traffic to port 30333.  
3. Restart the node and retest.

---

## 5. `no public IPv4 found`

**Cause**  
Only private or loopback addresses are returned.

**How to fix**

1. Verify your server has a real public IP:  
   ```bash
   curl ifconfig.me
   ```
2. Start the node with your public IP in `--public-addr`.  
3. If behind a router, set up port‑forwarding for 30333/tcp.  
4. Allow the port through any firewall.

---

## 6. `invalid multiaddr: ...`

**Cause**  
A listen address returned by the node is not a valid libp2p multiaddr.

**How to fix**

1. Inspect the addresses (see #2) – they must look like  
   `/ip4/<IP>/tcp/30333` or `/dns4/<host>/tcp/30333`.  
2. Remove or correct bad `--listen-addr` / `--public-addr` flags.  
3. Restart and retest after each change.

---

## 7. `dial error: ...`

**Cause**  
The gateway cannot open a TCP connection to your node at the advertised address.

**How to fix**

1. Test from a remote machine:  
   ```bash
   nc -vz <PUBLIC_IP> 30333
   ```  
   Failure indicates firewall or NAT blocking.

2. Confirm the node is listening:  
   ```bash
   ss -tuln | grep 30333
   ```

3. Open port 30333 in your firewall (e.g., `sudo ufw allow 30333/tcp`).  
4. Configure port‑forwarding if behind a router.

---

## 8. `handshake failed`

**Cause**  
Connection is made but the libp2p handshake times out or is incompatible.

**How to fix**

1. Search logs for handshake errors:  
   ```bash
   docker logs <container_name> | grep -i handshake
   ```
2. Ensure a stable network (low latency, low packet loss).  
3. Confirm you are on a compatible Bittensor version; upgrade if necessary.  
4. Restart both the node and the gateway (if you control it) or try registering through a different peer.

---

**Need more help?**  
If you have walked through all steps and still see errors:

- Compare your setup with the latest official Bittensor installation guides.  
- Join the Bittensor community Discord for peer support and live troubleshooting.
