#!/bin/bash
echo "=== leaf ==="
echo | openssl s_client -connect library.yonsei.ac.kr:443 -servername library.yonsei.ac.kr 2>/dev/null | openssl x509 -noout -issuer -subject
echo "=== chain depths ==="
echo | openssl s_client -connect library.yonsei.ac.kr:443 -servername library.yonsei.ac.kr -showcerts 2>/dev/null | grep -E "^ *(s|i):"
echo "=== verify ==="
echo | openssl s_client -connect library.yonsei.ac.kr:443 -servername library.yonsei.ac.kr 2>/dev/null | grep -i "verify"
