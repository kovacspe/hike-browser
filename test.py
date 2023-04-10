import requests

x = requests.get('https://en.mapy.cz/s/cafafetevo')
print(x.text)
