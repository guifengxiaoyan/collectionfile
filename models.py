from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin
from datetime import datetime, timezone, timedelta

db = SQLAlchemy()
login_manager = LoginManager()

def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))

class Admin(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

class Collector(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=beijing_now)

    collection_object = db.relationship('CollectionObject', back_populates='collector', uselist=False)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)

class ThemeObject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    theme_id = db.Column(db.Integer, db.ForeignKey('collection_theme.id'), nullable=False)
    object_id = db.Column(db.Integer, db.ForeignKey('collection_object.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    theme = db.relationship('CollectionTheme', backref=db.backref('theme_objects', lazy='dynamic', cascade='all, delete-orphan'))
    collection_object = db.relationship('CollectionObject', backref=db.backref('theme_links', lazy='dynamic', cascade='all, delete-orphan'))

class CollectionObject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    collector_id = db.Column(db.Integer, db.ForeignKey('collector.id'), nullable=True)

    collector = db.relationship('Collector', back_populates='collection_object')
    attachments = db.relationship('Attachment', backref='collection_object', lazy=True, cascade='all, delete-orphan')

    @property
    def themes(self):
        return [link.theme for link in self.theme_links]

    @property
    def has_attachments(self):
        return len(self.attachments) > 0

class CollectionTheme(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    announcement = db.Column(db.Text)
    deadline = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=beijing_now)
    is_active = db.Column(db.Boolean, default=True)
    collector_name = db.Column(db.String(100))

    attachments = db.relationship('ThemeAttachment', backref='theme', lazy=True, cascade='all, delete-orphan')

    @property
    def objects(self):
        return [link.collection_object for link in self.theme_objects]

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)
    attachments = db.relationship('AnnouncementAttachment', backref='announcement', lazy=True, cascade='all, delete-orphan')

class AnnouncementAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcement.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=beijing_now)

class ThemeAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    theme_id = db.Column(db.Integer, db.ForeignKey('collection_theme.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=beijing_now)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    collection_object_id = db.Column(db.Integer, db.ForeignKey('collection_object.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=beijing_now)

collector_login_manager = LoginManager()

@login_manager.user_loader
def load_admin_user(user_id):
    return Admin.query.get(int(user_id))

@collector_login_manager.user_loader
def load_collector_user(user_id):
    return Collector.query.get(int(user_id))
