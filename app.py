import os

from flask import Flask, render_template, redirect, send_from_directory
from models import Group, Hike
from manage import load_all

from settings import DATA_DIR
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


@app.route("/group/<slug>")
def group(slug: str):
    group = Group.load_by_slug(slug)
    return render_template(
        'group.html',
        group=group
    )


@app.route("/hike/<slug>")
def hike(slug: str):
    hike = Hike.load_by_slug(slug)
    if hike is not None:
        return render_template(
            'hike.html',
            hike=hike
        )
    else:
        return redirect('/')


@app.route('/photo/<slug>/<filename>')
def download_file(slug, filename):
    return send_from_directory(os.path.join(DATA_DIR, slug, 'img'), filename, as_attachment=False)
