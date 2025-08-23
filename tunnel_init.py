import os
from cloudflare import Cloudflare
import sys
import argparse
from base64 import b64encode, b64decode
from kubernetes import client, config
import json

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
CLOUDFLARE_ZONE = os.getenv("CLOUDFLARE_ZONE_NAME")
TUNNEL_NAME = os.getenv("TUNNEL_NAME", "dummy-tunnel")
CLOUDFLARE_SECRET_NAME = "cloudflared"
CLOUDFLARE_SECRET_NAMESPACE = "cloudflared"
DNS_REC_NAME = f'{TUNNEL_NAME}-cfargotunnel'

cfclient = Cloudflare(
    api_token=os.getenv("CF_API_TOKEN")
)

def get_tunnel_tokens(tunnel_id, debug=False):
    """
    Deletes a Cloudflare Tunnel from an account.
    params:
    - tunnel_name: name of the tunnel
    """
    if debug: print(tunnel_id)
    return cfclient.zero_trust.tunnels.cloudflared.token.get(
        tunnel_id = tunnel_id,
        account_id = CLOUDFLARE_ACCOUNT_ID
    )

def get_tunnel(tunnel_name: str):
    """
    Lists and filters Cloudflare Tunnels in an account.
    params:
    - tunnel_name: name of the tunnel
    """
    return cfclient.zero_trust.tunnels.cloudflared.list(
        account_id = CLOUDFLARE_ACCOUNT_ID,
        name = tunnel_name,
        is_deleted = False #exclude deleted tunnels
    )

def create_tunnel(tunnel_name: str, debug=False):
    """
    Creates a new Cloudflare Tunnel in an account.
    params:
    - tunnel_name: name of the tunnel
    """
    return cfclient.zero_trust.tunnels.cloudflared.create(
        account_id = CLOUDFLARE_ACCOUNT_ID,
        name = tunnel_name
    )

def ensure_secret_exists(credentials): 
    """
    Ensures secret exists in cluster.
    """
    try:
        config.load_incluster_config()   # use when running inside k8s
    except config.ConfigException:
        config.load_kube_config()        # fallback to local kubeconfig
    v1 = client.CoreV1Api()

    try:
        v1.read_namespaced_secret(CLOUDFLARE_SECRET_NAME, CLOUDFLARE_SECRET_NAMESPACE)
        print(f"Secret {CLOUDFLARE_SECRET_NAME} already exists")
        patch_body = {"data":{"credentials.json": credentials}}
        api_response = v1.patch_namespaced_secret(
            name=CLOUDFLARE_SECRET_NAME,
            namespace=CLOUDFLARE_SECRET_NAMESPACE,
            body=patch_body
        )
        print(f"Secret '{CLOUDFLARE_SECRET_NAME}' patched successfully.")
        print(api_response)
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"Creating Kubernetes secret {CLOUDFLARE_SECRET_NAME} in {CLOUDFLARE_SECRET_NAMESPACE}")
            # create namespaced secrets
            secret_manifest = client.V1Secret(
                api_version="v1",
                kind="Secret",
                metadata=client.V1ObjectMeta(name=CLOUDFLARE_SECRET_NAME),
                type="Opaque",
                data={"credentials.json": credentials},
            )
            api_response = v1.create_namespaced_secret(namespace=CLOUDFLARE_SECRET_NAMESPACE, body=secret_manifest)
            if api_response.metadata.resource_version and api_response.uid:
                print(f"Secret '{api_response.metadata.name}' created successfully in namespace '{api_response.metadata.namespace}'.")
        else:
            raise

def create_tunnel_dns_record(tunnel_id, debug=False):
    """
    Create tunnel DNS record if it doesn't exists
    """
    dns_record = cfclient.dns.records.list(
        zone_id = CLOUDFLARE_ZONE_ID,
        name = f'{DNS_REC_NAME}.{CLOUDFLARE_ZONE}',
        type = "CNAME"
    )
    if debug: print(dns_record)
    if dns_record.success and len(dns_record.result) > 0:
        print(f'tunnel DNS record already exist {DNS_REC_NAME}')
        return 
    else: 
        print(f'creating tunnel DNS record {DNS_REC_NAME}')

    dns_record = cfclient.dns.records.create(
        zone_id = CLOUDFLARE_ZONE_ID,
        name = DNS_REC_NAME,
        content = f'{tunnel_id}.cfargotunnel.com',
        type="CNAME",
        proxied=True
    )
    if debug: print(dns_record)
    if dns_record.id:
        print(f'tunnel DNS record {DNS_REC_NAME} created successfully.')


def delete_tunnel(tunnel_id, debug=False):
    """
    Deletes a Cloudflare Tunnel from an account.
    params:
    - tunnel_name: name of the tunnel
    """
    if debug: print(tunnel_id)
    return cfclient.zero_trust.tunnels.cloudflared.delete(
        tunnel_id = tunnel_id,
        account_id = CLOUDFLARE_ACCOUNT_ID
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', type=str, help='Create or Delete tunnel?', default="create")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode.")
    args = parser.parse_args()
    
    try:
        # check if tunnel exist 
        tunnel = get_tunnel(TUNNEL_NAME)
        if args.debug: print(f'list tunnel response: {tunnel}')
        # if tunnel do not exist, create tunnel
        if tunnel.success and len(tunnel.result) == 0:
            print(f"Tunnel {TUNNEL_NAME} not found, creating...")
            tunnel = create_tunnel(TUNNEL_NAME, args.debug)
            if args.debug: print(f'created tunnel response: {tunnel}')
            if tunnel.id and tunnel.name == TUNNEL_NAME:
                print(f'Tunnel {TUNNEL_NAME} successfully created.')
            else:
                sys.exit(f'Failed to create tunnel {TUNNEL_NAME}. Check the response {tunnel}')
            
            creds_b64 = b64encode(
                bytes(str(tunnel.credentials_file), "utf-8")
            ).decode("utf-8")

            # create secrets
            ensure_secret_exists(creds_b64)
            create_tunnel_dns_record(tunnel.id)

        else:
            # if tunnel exist, create tunnel
            tunnels = [t.id for t in tunnel.result]
            print(f"Tunnel {TUNNEL_NAME} already exists: { tunnel.result[0].id }")
            tokens = get_tunnel_tokens(tunnel.result[0].id)
            decoded_tokens = b64decode(tokens).decode('utf-8')
            parsed_creds = json.loads(decoded_tokens)
            credentials = {
                "AccountTag": parsed_creds["a"],
                "TunnelID":   parsed_creds["t"],
                "TunnelName": TUNNEL_NAME,   
                "TunnelSecret": parsed_creds["s"],
            }
            creds_b64 = b64encode(
                bytes(str(credentials), "utf-8")
            ).decode("utf-8")
            ensure_secret_exists(creds_b64)
            create_tunnel_dns_record(tunnel.result[0].id)
            # for tunnel in tunnels:
            #     tunnel_delete_resp = delete_tunnel(tunnel, args.debug)
            #     if args.debug: print(f'delete tunnel response: {tunnel}')
            #     tunnel_exists = get_tunnel(TUNNEL_NAME)
            #     if tunnel_exists.success and len(tunnel_exists.result) == 0:
            #         print(f'tunnel {TUNNEL_NAME} successfully deleted.') 
            #     else:
            #         print(f'failed to delete tunnel {TUNNEL_NAME}. Check the response {tunnel_delete_resp}')
   
    except Exception as e:
        print(f"Error: {e}")
        exit(1)