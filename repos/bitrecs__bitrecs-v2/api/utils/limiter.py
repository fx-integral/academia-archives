from slowapi import Limiter
from utils.network import get_client_ip

limiter = Limiter(key_func=get_client_ip)