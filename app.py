from flask import Flask, render_template
from models import Group, Hike
from manage import load_all
app = Flask(__name__)


@app.route("/")
def menu():
    hikes, groups = load_all()
    hikes = [hike.__dict__ for hike in hikes]
    groups = [group.__dict__ for group in groups]
    print(hikes)
    return render_template(
        'menu.html',
        groups=groups,
        hikes=hikes
    )


@app.route("/group/slug")
def group(slug: str):
    return render_template(
        'menu.html',
        groups=groups,
        hikes=hikes
    )


@app.route("/hike/slug")
def hike(slug: str):
    hike = Hike.load_from_folder(slug)
    return render_template(
        'hike.html',
        hike=hike,
    )
