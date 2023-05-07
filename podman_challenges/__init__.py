import hashlib
import json
import random
import tempfile
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from logging import getLogger

import requests
from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_restx import Namespace, Resource
from podman import PodmanClient
from werkzeug.utils import secure_filename
# from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FileField,
    HiddenField,
    PasswordField,
    RadioField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
# from wtforms import TextField, SubmitField, BooleanField, HiddenField, FileField, SelectMultipleField
from wtforms.validators import DataRequired, InputRequired, ValidationError

import CTFd.utils.scores
from CTFd.api import CTFd_API_v1
from CTFd.api.v1.challenges import Challenge, ChallengeList
from CTFd.api.v1.scoreboard import ScoreboardDetail
from CTFd.forms import BaseForm
from CTFd.forms.fields import SubmitField
from CTFd.models import (
    ChallengeFiles,
    Challenges,
    Fails,
    Files,
    Flags,
    Hints,
    Solves,
    Tags,
    Teams,
    Users,
    db,
    ma,
)
from CTFd.plugins import (
    bypass_csrf_protection,
    register_admin_plugin_menu_bar,
    register_plugin_assets_directory,
)
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge, get_chal_class
from CTFd.plugins.flags import get_flag_class
from CTFd.schemas.tags import TagSchema
from CTFd.utils.config import get_themes, is_teams_mode
from CTFd.utils.dates import unix_time
from CTFd.utils.decorators import (
    admins_only,
    authed_only,
    during_ctf_time_only,
    require_verified_emails,
)
from CTFd.utils.decorators.visibility import (
    check_challenge_visibility,
    check_score_visibility,
)
from CTFd.utils.uploads import delete_file
from CTFd.utils.user import authed, get_current_team, get_current_user, get_ip, is_admin

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podman.domain.containers import Container

logger = getLogger("podman_challenges")

class PodmanConfig(db.Model):
    """
	Podman Config Model. This model stores the config for podman API connections.
	"""
    id = db.Column(db.Integer, primary_key=True)
    
    uri = db.Column("uri", db.String(1024), index=True)

    # Identify file for SSH connection
    identity = db.Column("identity", db.String(256), index=True)

    # Identifier of connection to use from `XDG_CONFIG_HOME/containers/containers.conf`
    connection = db.Column("connection", db.String(256), index=True)


    repositories = db.Column("repositories", db.String(1024), index=True)



class PodmanChallengeTracker(db.Model):
    """
	Podman Container Tracker. This model stores the users/teams active podman containers.
	"""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column("team_id", db.String(64), index=True)
    user_id = db.Column("user_id", db.String(64), index=True)
    podman_image = db.Column("podman_image", db.String(64), index=True)
    timestamp = db.Column("timestamp", db.Integer, index=True)
    revert_time = db.Column("revert_time", db.Integer, index=True)
    instance_id = db.Column("instance_id", db.String(128), index=True)
    ports = db.Column('ports', db.String(128), index=True)
    uri = db.Column('uri', db.String(128), index=True)


class PodmanConfigForm(BaseForm):
    id = HiddenField()
    uri = StringField(
        "Podman URI", description="The URI used to connect to the local or remote podman instance"
    )

    identity = FileField("Identity File", description="Identity file to be used when using SSH as a transport")

    connection = StringField("Podman Connection Entry", description="Named connection entry from XDG_CONFIG_HOME/containers/containers.conf to use for podman connection")

    repositories = SelectMultipleField('Repositories')
    submit = SubmitField('Submit')


def define_podman_admin(app):
    admin_podman_config = Blueprint('admin_podman_config', __name__, template_folder='templates',
                                    static_folder='assets')

    @admin_podman_config.route("/admin/podman_config", methods=["GET", "POST"])
    @admins_only
    def podman_config():
        podman = PodmanConfig.query.filter_by(id=1).first()
        form = PodmanConfigForm()
        if request.method == "POST":
            if podman:
                b = podman
            else:
                b = PodmanConfig()
            try:
                identity = request.form['identity']
            except:
                print(traceback.print_exc())
                identity = ''
            try:
                connection = request.form['connection']
            except:
                print(traceback.print_exc())
                connection = ''

            if len(identity) != 0: b.identity = identity
            if len(connection) != 0: b.connection = connection
            
            b.uri = request.form['uri']

            try:
                b.repositories = ','.join(request.form.to_dict(flat=False)['repositories'])
            except:
                print(traceback.print_exc())
                b.repositories = None
            db.session.add(b)
            db.session.commit()
            podman = PodmanConfig.query.filter_by(id=1).first()

        try:
            repos = get_repositories(podman)
        except:
            print(traceback.print_exc())
            repos = list()
           
        if len(repos) == 0:
            form.repositories.choices = [("ERROR", "Failed to Connect to Podman")]
        else:
            form.repositories.choices = [(d, d) for d in repos]

        dconfig = PodmanConfig.query.first()
        try:
            selected_repos = dconfig.repositories
            if selected_repos == None:
                selected_repos = list()
        # selected_repos = dconfig.repositories.split(',')
        except:
            print(traceback.print_exc())
            selected_repos = []
        return render_template("podman_config.html", config=dconfig, form=form, repos=selected_repos)

    app.register_blueprint(admin_podman_config)


def define_podman_status(app):
    admin_podman_status = Blueprint('admin_podman_status', __name__, template_folder='templates',
                                    static_folder='assets')

    @admin_podman_status.route("/admin/podman_status", methods=["GET", "POST"])
    @admins_only
    def podman_admin():
        podman_config = PodmanConfig.query.filter_by(id=1).first()
        podman_tracker = PodmanChallengeTracker.query.all()
        for i in podman_tracker:
            if is_teams_mode():
                name = Teams.query.filter_by(id=i.team_id).first()
                i.team_id = name.name
            else:
                name = Users.query.filter_by(id=i.user_id).first()
                i.user_id = name.name
        return render_template("admin_podman_status.html", podmans=podman_tracker)

    app.register_blueprint(admin_podman_status)


kill_container = Namespace("nuke", description='Endpoint to nuke containers')


@kill_container.route("", methods=['POST', 'GET'])
class KillContainerAPI(Resource):
    @admins_only
    def get(self):
        container = request.args.get('container')
        full = request.args.get('all')
        podman_config = PodmanConfig.query.filter_by(id=1).first()
        podman_tracker = PodmanChallengeTracker.query.all()
        if full == "true":
            for c in podman_tracker:
                delete_container(podman_config, c.instance_id)
                PodmanChallengeTracker.query.filter_by(instance_id=c.instance_id).delete()
                db.session.commit()

        elif container != 'null' and container in [c.instance_id for c in podman_tracker]:
            delete_container(podman_config, container)
            PodmanChallengeTracker.query.filter_by(instance_id=container).delete()
            db.session.commit()

        else:
            return False
        return True


def get_client_cert(podman):
    try:
        ca = podman.ca_cert
        client = podman.client_cert
        ckey = podman.client_key
        ca_file = tempfile.NamedTemporaryFile(delete=False)
        ca_file.write(ca)
        ca_file.seek(0)
        client_file = tempfile.NamedTemporaryFile(delete=False)
        client_file.write(client)
        client_file.seek(0)
        key_file = tempfile.NamedTemporaryFile(delete=False)
        key_file.write(ckey)
        key_file.seek(0)
        CERT = (client_file.name, key_file.name)
    except:
        print(traceback.print_exc())
        CERT = None
    return CERT


# For the Podman Config Page. Gets the Current Repositories available on the Podman Server.f
def get_repositories(podman: PodmanConfig, tags: bool=False, repos: Optional[List]=None) -> List[str]:
    with PodmanClient(base_url=podman.uri) as client:
        images = client.images.list()

    result = list()
    for item in images:
        if item.tags:
            if repos:
                if not item.tags[0].split(':')[0] in repos:
                    continue
            if not tags:
                result.append(item.tags[0].split(':')[0])
            else:
                result.append(item.tags[0])
    return list(set(result))


def get_unavailable_ports(podman):
    with PodmanClient(base_url=podman.uri) as client:
        containers = client.containers.list()

    result = list()
    for item in containers:
        if item.ports:
            logger.error(item.ports)
            for k, v in item.ports.items():
                result.extend([p.HostPort for p in v])
    return result


def get_required_ports(podman: PodmanConfig, image: str) -> List[str]:
    with PodmanClient(base_url=podman.uri) as client:
        image = client.images.get(image)

    if not image:
        logger.error("Unable to find container image '%s'!", image)
        return []

    result = list(image.attrs.get("Config", {}).get("ExposedPorts", {}).keys())
    logger.debug("Image %s requires the following ports: %s", image.tags[0], result)

    return result


def create_container(podman: PodmanConfig, image: str, team: str, portbl: List[int]) -> "Container":
    needed_ports = get_required_ports(podman, image)
    team = hashlib.md5(team.encode("utf-8")).hexdigest()[:10]
    container_name = "%s_%s" % (image.split(':')[1], team)
    assigned_ports: List[int] = []

    bindings: Dict[str, int] = {}

    for entry in needed_ports:
        while True:
            assigned_port = random.choice(range(30000, 60000))
            if assigned_port not in portbl:
                bindings[entry] = assigned_port
                break

    container_config = {"name": container_name, "image": image, "ports": bindings }

    logger.error("Calling create container API with following args: %s", container_config)

    with PodmanClient(base_url=podman.uri) as client:
        container = client.containers.create(**container_config)

    return container


def delete_container(podman: PodmanConfig, instance_id: str) -> bool:

    with PodmanClient(base_url=podman.uri) as client:
        if client.containers.exists(instance_id):
            client.containers.get(instance_id).remove(force=True)
        
    return True


class PodmanChallengeType(BaseChallenge):
    id = "podman"
    name = "podman"
    templates = {
        'create': '/plugins/podman_challenges/assets/create.html',
        'update': '/plugins/podman_challenges/assets/update.html',
        'view': '/plugins/podman_challenges/assets/view.html',
    }
    scripts = {
        'create': '/plugins/podman_challenges/assets/create.js',
        'update': '/plugins/podman_challenges/assets/update.js',
        'view': '/plugins/podman_challenges/assets/view.js',
    }
    route = '/plugins/podman_challenges/assets'
    blueprint = Blueprint('podman_challenges', __name__, template_folder='templates', static_folder='assets')

    @staticmethod
    def update(challenge, request):
        """
		This method is used to update the information associated with a challenge. This should be kept strictly to the
		Challenges table and any child tables.

		:param challenge:
		:param request:
		:return:
		"""
        data = request.form or request.get_json()
        for attr, value in data.items():
            setattr(challenge, attr, value)

        db.session.commit()
        return challenge

    @staticmethod
    def delete(challenge):
        """
		This method is used to delete the resources used by a challenge.
		NOTE: Will need to kill all containers here

		:param challenge:
		:return:
		"""
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        PodmanChallenge.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    @staticmethod
    def read(challenge):
        """
		This method is in used to access the data of a challenge in a format processable by the front end.

		:param challenge:
		:return: Challenge object, data dictionary to be returned to the user
		"""
        challenge = PodmanChallenge.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'podman_image': challenge.podman_image,
            'description': challenge.description,
            'category': challenge.category,
            'state': challenge.state,
            'max_attempts': challenge.max_attempts,
            'type': challenge.type,
            'type_data': {
                'id': PodmanChallengeType.id,
                'name': PodmanChallengeType.name,
                'templates': PodmanChallengeType.templates,
                'scripts': PodmanChallengeType.scripts,
            }
        }
        return data

    @staticmethod
    def create(request):
        """
		This method is used to process the challenge creation request.

		:param request:
		:return:
		"""
        data = request.form or request.get_json()
        challenge = PodmanChallenge(**data)
        db.session.add(challenge)
        db.session.commit()
        return challenge

    @staticmethod
    def attempt(challenge, request):
        """
		This method is used to check whether a given input is right or wrong. It does not make any changes and should
		return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
		user's input from the request itself.

		:param challenge: The Challenge object from the database
		:param request: The request the user submitted
		:return: (boolean, string)
		"""

        data = request.form or request.get_json()
        print(request.get_json())
        print(data)
        submission = data["submission"].strip()
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        for flag in flags:
            if get_flag_class(flag.type).compare(flag, submission):
                return True, "Correct"
        return False, "Incorrect"

    @staticmethod
    def solve(user, team, challenge, request):
        """
		This method is used to insert Solves into the database in order to mark a challenge as solved.

		:param team: The Team object from the database
		:param chal: The Challenge object from the database
		:param request: The request the user submitted
		:return:
		"""
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        podman = PodmanConfig.query.filter_by(id=1).first()
        try:
            if is_teams_mode():
                podman_containers = PodmanChallengeTracker.query.filter_by(
                    podman_image=challenge.podman_image).filter_by(team_id=team.id).first()
            else:
                podman_containers = PodmanChallengeTracker.query.filter_by(
                    podman_image=challenge.podman_image).filter_by(user_id=user.id).first()
            
            delete_container(podman, podman_containers.instance_id)
            PodmanChallengeTracker.query.filter_by(instance_id=podman_containers.instance_id).delete()
        except:
            pass
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission,
        )
        db.session.add(solve)
        db.session.commit()
        # trying if this solces the detached instance error...
        #db.session.close()

    @staticmethod
    def fail(user, team, challenge, request):
        """
		This method is used to insert Fails into the database in order to mark an answer incorrect.

		:param team: The Team object from the database
		:param chal: The Challenge object from the database
		:param request: The request the user submitted
		:return:
		"""
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        wrong = Fails(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(request),
            provided=submission,
        )
        db.session.add(wrong)
        db.session.commit()
        #db.session.close()


class PodmanChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'podman'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    podman_image = db.Column(db.String(128), index=True)


# API
container_namespace = Namespace("container", description='Endpoint to interact with containers')


@container_namespace.route("", methods=['POST', 'GET'])
class ContainerAPI(Resource):
    @authed_only
    # I wish this was Post... Issues with API/CSRF and whatnot. Open to a Issue solving this.
    def get(self):
        container = request.args.get('name')
        if not container:
            return abort(403)
        podman = PodmanConfig.query.filter_by(id=1).first()
        containers = PodmanChallengeTracker.query.all()
        if container not in get_repositories(podman, tags=True):
            return abort(403)
        if is_teams_mode():
            session = get_current_team()
            # First we'll delete all old podman containers (+2 hours)
            for i in containers:
                if int(session.id) == int(i.team_id) and (unix_time(datetime.utcnow()) - int(i.timestamp)) >= 7200:
                    delete_container(podman, i.instance_id)
                    PodmanChallengeTracker.query.filter_by(instance_id=i.instance_id).delete()
                    db.session.commit()
            check = PodmanChallengeTracker.query.filter_by(team_id=session.id).filter_by(podman_image=container).first()
        else:
            session = get_current_user()
            for i in containers:
                if int(session.id) == int(i.user_id) and (unix_time(datetime.utcnow()) - int(i.timestamp)) >= 7200:
                    delete_container(podman, i.instance_id)
                    PodmanChallengeTracker.query.filter_by(instance_id=i.instance_id).delete()
                    db.session.commit()
            check = PodmanChallengeTracker.query.filter_by(user_id=session.id).filter_by(podman_image=container).first()
        # If this container is already created, we don't need another one.
        if check != None and not (unix_time(datetime.utcnow()) - int(check.timestamp)) >= 300:
            return abort(403)
        # The exception would be if we are reverting a box. So we'll delete it if it exists and has been around for more than 5 minutes.
        elif check != None:
            delete_container(podman, check.instance_id)
            if is_teams_mode():
                PodmanChallengeTracker.query.filter_by(team_id=session.id).filter_by(podman_image=container).delete()
            else:
                PodmanChallengeTracker.query.filter_by(user_id=session.id).filter_by(podman_image=container).delete()
            db.session.commit()
        portsbl = get_unavailable_ports(podman)
        created: Container = create_container(podman, container, session.name, portsbl)
        ports = created.ports.values()

        logger.warn("Ports: %s", ports)

        entry = PodmanChallengeTracker(
            team_id=session.id if is_teams_mode() else None,
            user_id=session.id if not is_teams_mode() else None,
            podman_image=container,
            timestamp=unix_time(datetime.utcnow()),
            revert_time=unix_time(datetime.utcnow()) + 300,
            instance_id=created.id,
            ports=','.join([p[0]['HostPort'] for p in ports]),
            uri=str(podman.uri)
        )
        db.session.add(entry)
        db.session.commit()
        #db.session.close()
        return


active_podman_namespace = Namespace("podman", description='Endpoint to retrieve User Podman Image Status')


@active_podman_namespace.route("", methods=['POST', 'GET'])
class PodmanStatus(Resource):
    """
	The Purpose of this API is to retrieve a public JSON string of all podman containers
	in use by the current team/user.
	"""

    @authed_only
    def get(self):
        podman = PodmanConfig.query.filter_by(id=1).first()
        if is_teams_mode():
            session = get_current_team()
            tracker = PodmanChallengeTracker.query.filter_by(team_id=session.id)
        else:
            session = get_current_user()
            tracker = PodmanChallengeTracker.query.filter_by(user_id=session.id)
        data = list()
        for i in tracker:
            data.append({
                'id': i.id,
                'team_id': i.team_id,
                'user_id': i.user_id,
                'podman_image': i.podman_image,
                'timestamp': i.timestamp,
                'revert_time': i.revert_time,
                'instance_id': i.instance_id,
                'ports': i.ports.split(','),
                'host': str(podman.hostname).split(':')[0]
            })
        return {
            'success': True,
            'data': data
        }


podman_namespace = Namespace("podman", description='Endpoint to retrieve podmanstuff')


@podman_namespace.route("", methods=['POST', 'GET'])
class PodmanAPI(Resource):
    """
	This is for creating Podman Challenges. The purpose of this API is to populate the Podman Image Select form
	object in the Challenge Creation Screen.
	"""

    @admins_only
    def get(self):
        podman = PodmanConfig.query.filter_by(id=1).first()
        images = get_repositories(podman, tags=True, repos=podman.repositories)
        if images:
            data = list()
            for i in images:
                data.append({'name': i})
            return {
                'success': True,
                'data': data
            }
        else:
            return {
                       'success': False,
                       'data': [
                           {
                               'name': 'Error in Podman Config!'
                           }
                       ]
                   }, 400


def load(app):
    app.db.create_all()
    CHALLENGE_CLASSES['podman'] = PodmanChallengeType
    register_plugin_assets_directory(app, base_path='/plugins/podman_challenges/assets')
    define_podman_admin(app)
    define_podman_status(app)
    CTFd_API_v1.add_namespace(podman_namespace, '/podman')
    CTFd_API_v1.add_namespace(container_namespace, '/container')
    CTFd_API_v1.add_namespace(active_podman_namespace, '/podman_status')
    CTFd_API_v1.add_namespace(kill_container, '/nuke')
