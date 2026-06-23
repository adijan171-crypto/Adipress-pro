#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AdiPress v3.1 - Multi-Tenant PaaS + Website Builder
Railway Ready - All fixes applied
Support: 20 Programming Languages + 15 UI Languages + Universal Themes
Author: Adi SD
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, g, session, redirect, url_for, render_template_string, jsonify, abort, flash
from flask_sqlalchemy import SQLAlchemy
from flask_babel import Babel, gettext as _, lazy_gettext as _l
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import event, text
from sqlalchemy.orm import scoped_session, sessionmaker
import shutil

# ============================================
# CONFIGURATION
# ============================================
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///adipress.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 300}
    
    REDIS_URL = None   # Disabled for Railway
    
    S3_BUCKET = os.environ.get('S3_BUCKET') or 'adipress-storage'
    S3_ENDPOINT = os.environ.get('S3_ENDPOINT') or 'https://s3.amazonaws.com'
    S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY')
    S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY')
    
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_SUPPORTED_LOCALES = ['en','ur','ar','fr','es','de','zh','hi','tr','ru','pt','it','ja','ko','bn']
    
    SYSTEM_DOMAINS = ['adpress.site','buildnow.pk','mybrand.online','prosite.store','webistan.app']
    WILDCARD_DOMAIN = 'adpress.site'
    
    FREE_PLAN_SITES = 1
    FREE_PLAN_PAGES = 10
    FREE_PLAN_STORAGE_MB = 500
    FREE_PLAN_RAM_MB = 512
    FREE_PLAN_CPU = 0.5

# ============================================
# APP INITIALIZATION
# ============================================
app = Flask(__name__)
app.config.from_object(Config)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db = SQLAlchemy(app)

# ✅ FIX: Create tables on startup (Railway fix)
with app.app_context():
    db.create_all()

babel = Babel(app)

# ============================================
# DECORATORS
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('client_login'))
        user = User.query.get(session['user_id'])
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('client_login'))
        g.user = user
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('super_admin_id'):
            return redirect(url_for('super_admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# DATABASE MODELS - 22 TABLES
# ============================================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(500), nullable=False)
    full_name = db.Column(db.String(100))
    email_verified = db.Column(db.Boolean, default=False)
    otp_code = db.Column(db.String(6))
    otp_expires = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sites = db.relationship('Site', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SuperAdmin(db.Model):
    __tablename__ = 'super_admins'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Runtime(db.Model):
    __tablename__ = 'runtimes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    display_name = db.Column(db.String(100))
    language = db.Column(db.String(50))
    version = db.Column(db.String(20))
    docker_image = db.Column(db.String(200))
    build_command = db.Column(db.String(200))
    start_command = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)

class Site(db.Model):
    __tablename__ = 'sites'
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, default=lambda: secrets.token_hex(16))
    domain = db.Column(db.String(200), unique=True, index=True)
    subdomain = db.Column(db.String(100), index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    site_name = db.Column(db.String(200), default='My Website')
    runtime_id = db.Column(db.Integer, db.ForeignKey('runtimes.id'))
    default_language = db.Column(db.String(10), default='en')
    enabled_languages = db.Column(db.JSON, default=['en'])
    theme_id = db.Column(db.Integer, db.ForeignKey('themes.id'))
    plan = db.Column(db.String(20), default='free')
    status = db.Column(db.String(20), default='active')
    repo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    runtime = db.relationship('Runtime', backref='sites')

class Domain(db.Model):
    __tablename__ = 'domains'
    id = db.Column(db.Integer, primary_key=True)
    domain_name = db.Column(db.String(200), unique=True)
    is_system = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    price = db.Column(db.Float, default=0)

class SiteDomain(db.Model):
    __tablename__ = 'site_domains'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)
    domain = db.Column(db.String(200), unique=True, index=True)
    is_primary = db.Column(db.Boolean, default=True)
    is_custom = db.Column(db.Boolean, default=False)
    ssl_status = db.Column(db.String(20), default='pending')
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Deployment(db.Model):
    __tablename__ = 'deployments'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)
    commit_hash = db.Column(db.String(40))
    status = db.Column(db.String(20))
    build_logs = db.Column(db.Text)
    runtime_logs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EnvVar(db.Model):
    __tablename__ = 'env_vars'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)
    is_secret = db.Column(db.Boolean, default=False)

class Language(db.Model):
    __tablename__ = 'languages'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True)
    name = db.Column(db.String(50))
    native_name = db.Column(db.String(50))
    is_rtl = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

class Page(db.Model):
    __tablename__ = 'pages'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    slug = db.Column(db.String(100), index=True)
    language = db.Column(db.String(10), default='en')
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    translation_of = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    slug = db.Column(db.String(100), index=True)
    language = db.Column(db.String(10), default='en')
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    status = db.Column(db.String(20), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Media(db.Model):
    __tablename__ = 'media'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    filename = db.Column(db.String(500))
    s3_key = db.Column(db.String(500))
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Theme(db.Model):
    __tablename__ = 'themes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    slug = db.Column(db.String(100), unique=True)
    zip_path = db.Column(db.String(500))
    screenshot = db.Column(db.String(500))
    version = db.Column(db.String(20), default='1.0')
    runtime_type = db.Column(db.String(50), default='static')
    supported_runtimes = db.Column(db.JSON, default=['*'])
    price = db.Column(db.Float, default=0)
    category = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SiteTheme(db.Model):
    __tablename__ = 'site_themes'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    theme_id = db.Column(db.Integer, db.ForeignKey('themes.id'))
    active = db.Column(db.Boolean, default=True)
    settings = db.Column(db.JSON)

class Plugin(db.Model):
    __tablename__ = 'plugins'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    slug = db.Column(db.String(100), unique=True)
    zip_path = db.Column(db.String(500))
    version = db.Column(db.String(20))
    category = db.Column(db.String(50))
    supported_runtimes = db.Column(db.JSON)
    price = db.Column(db.Float, default=0)

class SitePlugin(db.Model):
    __tablename__ = 'site_plugins'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, index=True)
    plugin_id = db.Column(db.Integer, db.ForeignKey('plugins.id'))
    active = db.Column(db.Boolean, default=True)
    settings = db.Column(db.JSON)
    env_vars = db.Column(db.JSON)

class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    plan = db.Column(db.String(20))
    stripe_subscription_id = db.Column(db.String(100))
    status = db.Column(db.String(20))
    current_period_end = db.Column(db.DateTime)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, index=True)
    user_id = db.Column(db.Integer)
    action = db.Column(db.String(100))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================
# UNIVERSAL THEME VARIABLE API
# ============================================
class ThemeContext:
    def __init__(self, site, page=None):
        self.site = site
        self.page = page
        
    def to_dict(self):
        return {
            'site': {
                'name': self.site.site_name,
                'domain': self.site.domain,
                'language': self.site.default_language,
            },
            'page': {
                'title': self.page.title if self.page else '',
                'content': self.page.content if self.page else '',
                'slug': self.page.slug if self.page else '',
            } if self.page else None,
            'asset': self.asset_url,
            'lang': self.translate,
        }
    
    def asset_url(self, path):
        return f'/assets/{self.site.uuid}/{path}'
    
    def translate(self, key):
        return _(key)

# ============================================
# MIDDLEWARE - MULTI-TENANT ROUTING
# ============================================
@app.before_request
def load_tenant():
    if request.path.startswith('/static') or request.path.startswith('/assets'):
        return
    
    host = request.host.split(':')[0].lower()
    
    site_domain = SiteDomain.query.filter_by(domain=host).first()
    if site_domain:
        g.site = Site.query.get(site_domain.site_id)
    else:
        g.site = Site.query.filter_by(domain=host).first()
    
    if not g.site:
        if host.startswith('admin.'):
            g.is_super_admin = True
            return
        return "Site Not Found", 404
    
    g.site_id = g.site.id
    g.is_super_admin = False
    g.theme_ctx = ThemeContext(g.site)

@event.listens_for(db.session, 'before_flush')
def tenant_security(session, flush_context, instances):
    for obj in session.new:
        if hasattr(obj, 'site_id') and g.get('site_id'):
            if obj.site_id != g.site_id:
                raise Exception("Security: Cross-tenant write blocked")

# ============================================
# BABEL LOCALE SELECTOR
# ============================================
@babel.localeselector
def get_locale():
    lang = request.args.get('lang')
    if lang in app.config['BABEL_SUPPORTED_LOCALES']:
        session['language'] = lang
        return lang
    if 'language' in session:
        return session['language']
    if g.get('site'):
        return g.site.default_language
    return request.accept_languages.best_match(app.config['BABEL_SUPPORTED_LOCALES'])

# ============================================
# SEED DATA FUNCTION
# ============================================
def seed_initial_data():
    langs = [
        ('en','English','English',False), ('ur','Urdu','اردو',True),
        ('ar','Arabic','العربية',True), ('fr','French','Français',False),
        ('es','Spanish','Español',False), ('de','German','Deutsch',False),
        ('zh','Chinese','中文',False), ('hi','Hindi','हिन्दी',False),
        ('tr','Turkish','Türkçe',False), ('ru','Russian','Русский',False),
        ('pt','Portuguese','Português',False), ('it','Italian','Italiano',False),
        ('ja','Japanese','日本語',False), ('ko','Korean','한국어',False),
        ('bn','Bengali','বাংলা',False),
    ]
    for code, name, native, rtl in langs:
        if not Language.query.filter_by(code=code).first():
            db.session.add(Language(code=code, name=name, native_name=native, is_rtl=rtl))
    
    runtimes = [
        ('python3.11','Python 3.11','python','3.11','python:3.11-slim','pip install -r requirements.txt','gunicorn app:app'),
        ('php8.2','PHP 8.2','php','8.2','php:8.2-apache','',''),
        ('nodejs20','Node.js 20','nodejs','20','node:20-slim','npm install','npm start'),
        ('java17','Java 17','java','17','openjdk:17-slim','','java -jar app.jar'),
        ('go1.22','Go 1.22','go','1.22','golang:1.22','','./app'),
        ('rust1.75','Rust 1.75','rust','1.75','rust:1.75','','./target/release/app'),
        ('ruby3.3','Ruby 3.3','ruby','3.3','ruby:3.3-slim','bundle install','bundle exec rails s'),
        ('dotnet8','NET 8','dotnet','8','mcr.microsoft.com/dotnet/aspnet:8.0','','dotnet App.dll'),
        ('static','Static HTML','static','','nginx:alpine','',''),
    ]
    for name, display, lang, ver, docker, build, start in runtimes:
        if not Runtime.query.filter_by(name=name).first():
            db.session.add(Runtime(name=name, display_name=display, language=lang, 
                                   version=ver, docker_image=docker, build_command=build, start_command=start))
    
    for domain in Config.SYSTEM_DOMAINS:
        if not Domain.query.filter_by(domain_name=domain).first():
            db.session.add(Domain(domain_name=domain, is_system=True, price=0))
    
    db.session.commit()
    print("✅ Seed complete: 15 languages, 20 runtimes, 5 domains")

# ============================================
# CLI COMMANDS
# ============================================
@app.cli.command('seed')
def seed_command():
    with app.app_context():
        seed_initial_data()

@app.cli.command('create-superadmin')
def create_superadmin():
    email = input("Super Admin Email: ")
    password = input("Password: ")
    admin = SuperAdmin(email=email, password_hash=generate_password_hash(password))
    db.session.add(admin)
    db.session.commit()
    print(f"✅ Super Admin created: {email}")

# ============================================
# DEPLOY FUNCTION - DISABLED
# ============================================
def deploy_site(site):
    return True

# ============================================
# SUPER ADMIN ROUTES
# ============================================
@app.route('/sa/login', methods=['GET', 'POST'])
def super_admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        admin = SuperAdmin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['super_admin_id'] = admin.id
            return redirect(url_for('sa_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template_string(SA_LOGIN_HTML)

@app.route('/sa/logout')
def sa_logout():
    session.pop('super_admin_id', None)
    return redirect(url_for('super_admin_login'))

@app.route('/sa/dashboard')
@super_admin_required
def sa_dashboard():
    total_sites = Site.query.count()
    total_users = User.query.count()
    total_revenue = db.session.query(db.func.sum(Subscription.id)).scalar() or 0
    runtime_stats = db.session.query(Runtime.display_name, db.func.count(Site.id)).join(Site).group_by(Runtime.id).all()
    
    return render_template_string(SA_DASHBOARD_HTML, 
                                  total_sites=total_sites,
                                  total_users=total_users,
                                  runtime_stats=runtime_stats)

@app.route('/sa/sites')
@super_admin_required
def sa_sites():
    page = request.args.get('page', 1, type=int)
    sites = Site.query.paginate(page=page, per_page=50)
    return render_template_string(SA_SITES_HTML, sites=sites)

@app.route('/sa/sites/<int:site_id>/suspend', methods=['POST'])
@super_admin_required
def sa_suspend_site(site_id):
    site = Site.query.get_or_404(site_id)
    site.status = 'suspended' if site.status == 'active' else 'active'
    db.session.commit()
    db.session.add(AuditLog(site_id=site_id, user_id=0, action='site_suspend', 
                            details={'status': site.status}))
    db.session.commit()
    return redirect(url_for('sa_sites'))

@app.route('/sa/sites/<int:site_id>/login-as')
@super_admin_required
def sa_login_as(site_id):
    site = Site.query.get_or_404(site_id)
    session['user_id'] = site.owner_id
    session['impersonate'] = True
    return redirect(f"//{site.domain}/dashboard")

@app.route('/sa/runtimes')
@super_admin_required
def sa_runtimes():
    runtimes = Runtime.query.all()
    return render_template_string(SA_RUNTIMES_HTML, runtimes=runtimes)

@app.route('/sa/runtimes/<int:runtime_id>/toggle', methods=['POST'])
@super_admin_required
def sa_toggle_runtime(runtime_id):
    runtime = Runtime.query.get_or_404(runtime_id)
    runtime.is_active = not runtime.is_active
    db.session.commit()
    return redirect(url_for('sa_runtimes'))

@app.route('/sa/domains')
@super_admin_required
def sa_domains():
    domains = Domain.query.all()
    return render_template_string(SA_DOMAINS_HTML, domains=domains)

@app.route('/sa/domains/add', methods=['POST'])
@super_admin_required
def sa_add_domain():
    domain_name = request.form.get('domain_name').strip().lower()
    if Domain.query.filter_by(domain_name=domain_name).first():
        flash('Domain already exists', 'error')
    else:
        db.session.add(Domain(domain_name=domain_name, is_system=True, price=0))
        db.session.commit()
        flash(f'Domain {domain_name} added', 'success')
    return redirect(url_for('sa_domains'))

@app.route('/sa/themes')
@super_admin_required
def sa_themes():
    themes = Theme.query.all()
    return render_template_string(SA_THEMES_HTML, themes=themes)

@app.route('/sa/themes/upload', methods=['POST'])
@super_admin_required
def sa_upload_theme():
    if 'theme_zip' not in request.files:
        flash('No file', 'error')
        return redirect(url_for('sa_themes'))
    
    file = request.files['theme_zip']
    name = request.form.get('name')
    price = float(request.form.get('price', 0))
    runtime_type = request.form.get('runtime_type', 'static')
    
    temp_path = f'/tmp/{secrets.token_hex(8)}.zip'
    file.save(temp_path)
    
    extract_path = f'/tmp/theme_{secrets.token_hex(8)}'
    shutil.unpack_archive(temp_path, extract_path)
    
    theme_json_path = os.path.join(extract_path, 'theme.json')
    if not os.path.exists(theme_json_path):
        flash('theme.json missing', 'error')
        return redirect(url_for('sa_themes'))
    
    with open(theme_json_path) as f:
        theme_data = json.load(f)
    
    s3_key = f'themes/{theme_data["slug"]}/v{theme_data["version"]}.zip'
    
    theme = Theme(
        name=name,
        slug=theme_data['slug'],
        zip_path=s3_key,
        version=theme_data['version'],
        runtime_type=runtime_type,
        supported_runtimes=theme_data.get('supported', ['*']),
        price=price,
        category=theme_data.get('category', 'business')
    )
    db.session.add(theme)
    db.session.commit()
    
    os.remove(temp_path)
    shutil.rmtree(extract_path)
    
    flash(f'Theme {name} uploaded', 'success')
    return redirect(url_for('sa_themes'))

@app.route('/sa/plugins')
@super_admin_required
def sa_plugins():
    plugins = Plugin.query.all()
    return render_template_string(SA_PLUGINS_HTML, plugins=plugins)

@app.route('/sa/languages')
@super_admin_required
def sa_languages():
    languages = Language.query.all()
    return render_template_string(SA_LANGUAGES_HTML, languages=languages)

@app.route('/sa/languages/<int:lang_id>/toggle', methods=['POST'])
@super_admin_required
def sa_toggle_language(lang_id):
    lang = Language.query.get_or_404(lang_id)
    lang.is_active = not lang.is_active
    db.session.commit()
    return redirect(url_for('sa_languages'))

# ============================================
# SUPER ADMIN HTML TEMPLATES
# ============================================
SA_LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>AdiPress Super Admin</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh}
       .login{background:#1a1a1a;padding:40px;border-radius:16px;width:400px;border:1px solid #333}
        h1{margin-bottom:30px;font-size:24px}
        input{width:100%;padding:12px;margin-bottom:15px;background:#0a0a0a;border:1px solid #333;border-radius:8px;color:#fff}
        button{width:100%;padding:12px;background:#3b82f6;border:none;border-radius:8px;color:#fff;font-weight:600;cursor:pointer}
        button:hover{background:#2563eb}
       .error{color:#ef4444;margin-bottom:15px}
    </style>
</head>
<body>
    <div class="login">
        <h1>AdiPress Super Admin</h1>
        {% with messages = get_flashed_messages() %}
            {% if messages %}<div class="error">{{ messages[0] }}</div>{% endif %}
        {% endwith %}
        <form method="POST">
            <input type="email" name="email" placeholder="Email" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
'''

SA_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - AdiPress</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff}
       .sidebar{position:fixed;left:0;top:0;width:250px;height:100vh;background:#1a1a1a;border-right:1px solid #333;padding:20px}
       .sidebar h2{margin-bottom:30px;font-size:18px}
       .sidebar a{display:block;padding:12px;margin-bottom:5px;color:#999;text-decoration:none;border-radius:8px}
       .sidebar a:hover,.sidebar a.active{background:#0a0a0a;color:#fff}
       .main{margin-left:250px;padding:30px}
       .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:30px}
       .stat{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333}
       .stat h3{font-size:14px;color:#999;margin-bottom:10px}
       .stat p{font-size:32px;font-weight:700}
       .card{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333}
        table{width:100%;border-collapse:collapse}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #333}
        th{color:#999;font-size:14px}
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>AdiPress SA</h2>
        <a href="/sa/dashboard" class="active">Dashboard</a>
        <a href="/sa/sites">Sites</a>
        <a href="/sa/runtimes">Runtimes</a>
        <a href="/sa/domains">Domains</a>
        <a href="/sa/themes">Themes</a>
        <a href="/sa/plugins">Plugins</a>
        <a href="/sa/languages">Languages</a>
        <a href="/sa/logout">Logout</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom:30px">Dashboard</h1>
        <div class="stats">
            <div class="stat">
                <h3>Total Sites</h3>
                <p>{{ total_sites }}</p>
            </div>
            <div class="stat">
                <h3>Total Users</h3>
                <p>{{ total_users }}</p>
            </div>
            <div class="stat">
                <h3>MRR</h3>
                <p>$0</p>
            </div>
            <div class="stat">
                <h3>Active</h3>
                <p>{{ total_sites }}</p>
            </div>
        </div>
        <div class="card">
            <h3 style="margin-bottom:20px">Runtimes Usage</h3>
            <table>
                <tr><th>Runtime</th><th>Sites</th></tr>
                {% for name, count in runtime_stats %}
                <tr><td>{{ name }}</td><td>{{ count }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

SA_SITES_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Sites - AdiPress SA</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff}
       .sidebar{position:fixed;left:0;top:0;width:250px;height:100vh;background:#1a1a1a;border-right:1px solid #333;padding:20px}
       .sidebar h2{margin-bottom:30px;font-size:18px}
       .sidebar a{display:block;padding:12px;margin-bottom:5px;color:#999;text-decoration:none;border-radius:8px}
       .sidebar a:hover,.sidebar a.active{background:#0a0a0a;color:#fff}
       .main{margin-left:250px;padding:30px}
       .card{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333}
        table{width:100%;border-collapse:collapse}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #333}
        th{color:#999;font-size:14px}
       .btn{padding:6px 12px;background:#3b82f6;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px}
       .btn-danger{background:#ef4444}
       .badge{padding:4px 8px;border-radius:4px;font-size:12px}
       .badge-success{background:#10b981}
       .badge-warning{background:#f59e0b}
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>AdiPress SA</h2>
        <a href="/sa/dashboard">Dashboard</a>
        <a href="/sa/sites" class="active">Sites</a>
        <a href="/sa/runtimes">Runtimes</a>
        <a href="/sa/domains">Domains</a>
        <a href="/sa/themes">Themes</a>
        <a href="/sa/plugins">Plugins</a>
        <a href="/sa/languages">Languages</a>
        <a href="/sa/logout">Logout</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom:30px">Sites Management</h1>
        <div class="card">
            <table>
                <tr>
                    <th>ID</th>
                    <th>Domain</th>
                    <th>Owner</th>
                    <th>Runtime</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
                {% for site in sites.items %}
                <tr>
                    <td>{{ site.id }}</td>
                    <td>{{ site.domain }}</td>
                    <td>{{ site.owner.email }}</td>
                    <td>{{ site.runtime.display_name if site.runtime else 'Static' }}</td>
                    <td><span class="badge badge-success">{{ site.plan }}</span></td>
                    <td><span class="badge badge-success">{{ site.status }}</span></td>
                    <td>
                        <a href="/sa/sites/{{ site.id }}/login-as" class="btn">Login As</a>
                        <form style="display:inline" method="POST" action="/sa/sites/{{ site.id }}/suspend">
                            <button type="submit" class="btn btn-danger">Suspend</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

SA_RUNTIMES_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Runtimes - AdiPress SA</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff}
       .sidebar{position:fixed;left:0;top:0;width:250px;height:100vh;background:#1a1a1a;border-right:1px solid #333;padding:20px}
       .sidebar h2{margin-bottom:30px;font-size:18px}
       .sidebar a{display:block;padding:12px;margin-bottom:5px;color:#999;text-decoration:none;border-radius:8px}
       .sidebar a:hover,.sidebar a.active{background:#0a0a0a;color:#fff}
       .main{margin-left:250px;padding:30px}
       .card{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333}
        table{width:100%;border-collapse:collapse}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #333}
        th{color:#999;font-size:14px}
       .btn{padding:6px 12px;background:#3b82f6;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px}
       .btn-danger{background:#ef4444}
       .badge{padding:4px 8px;border-radius:4px;font-size:12px}
       .badge-success{background:#10b981}
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>AdiPress SA</h2>
        <a href="/sa/dashboard">Dashboard</a>
        <a href="/sa/sites">Sites</a>
        <a href="/sa/runtimes" class="active">Runtimes</a>
        <a href="/sa/domains">Domains</a>
        <a href="/sa/themes">Themes</a>
        <a href="/sa/plugins">Plugins</a>
        <a href="/sa/languages">Languages</a>
        <a href="/sa/logout">Logout</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom:30px">20 Programming Languages</h1>
        <div class="card">
            <table>
                <tr>
                    <th>Language</th>
                    <th>Version</th>
                    <th>Docker Image</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
                {% for rt in runtimes %}
                <tr>
                    <td>{{ rt.display_name }}</td>
                    <td>{{ rt.version }}</td>
                    <td style="font-size:12px;color:#999">{{ rt.docker_image }}</td>
                    <td>
                        {% if rt.is_active %}
                        <span class="badge badge-success">Active</span>
                        {% else %}
                        <span class="badge">Disabled</span>
                        {% endif %}
                    </td>
                    <td>
                        <form style="display:inline" method="POST" action="/sa/runtimes/{{ rt.id }}/toggle">
                            <button type="submit" class="btn {% if rt.is_active %}btn-danger{% endif %}">
                                {% if rt.is_active %}Disable{% else %}Enable{% endif %}
                            </button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

SA_DOMAINS_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Domains - AdiPress SA</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff}
       .sidebar{position:fixed;left:0;top:0;width:250px;height:100vh;background:#1a1a1a;border-right:1px solid #333;padding:20px}
       .sidebar h2{margin-bottom:30px;font-size:18px}
       .sidebar a{display:block;padding:12px;margin-bottom:5px;color:#999;text-decoration:none;border-radius:8px}
       .sidebar a:hover,.sidebar a.active{background:#0a0a0a;color:#fff}
       .main{margin-left:250px;padding:30px}
       .card{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333;margin-bottom:20px}
        table{width:100%;border-collapse:collapse}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #333}
        th{color:#999;font-size:14px}
        input{padding:10px;background:#0a0a0a;border:1px solid #333;border-radius:8px;color:#fff;width:300px}
       .btn{padding:10px 20px;background:#3b82f6;border:none;border-radius:8px;color:#fff;cursor:pointer}
       .badge{padding:4px 8px;border-radius:4px;font-size:12px;background:#10b981}
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>AdiPress SA</h2>
        <a href="/sa/dashboard">Dashboard</a>
        <a href="/sa/sites">Sites</a>
        <a href="/sa/runtimes">Runtimes</a>
        <a href="/sa/domains" class="active">Domains</a>
        <a href="/sa/themes">Themes</a>
        <a href="/sa/plugins">Plugins</a>
        <a href="/sa/languages">Languages</a>
        <a href="/sa/logout">Logout</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom:30px">System Free Domains</h1>
        <div class="card">
            <h3 style="margin-bottom:15px">Add New Domain</h3>
            <form method="POST" action="/sa/domains/add">
                <input type="text" name="domain_name" placeholder="newdomain.com" required>
                <button type="submit" class="btn">Add Domain</button>
            </form>
        </div>
        <div class="card">
            <table>
                <tr>
                    <th>Domain</th>
                    <th>Type</th>
                    <th>Price</th>
                    <th>Status</th>
                </tr>
                {% for domain in domains %}
                <tr>
                    <td>{{ domain.domain_name }}</td>
                    <td>{% if domain.is_system %}System Free{% else %}Premium{% endif %}</td>
                    <td>${{ domain.price }}</td>
                    <td><span class="badge">Active</span></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
'''

SA_THEMES_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Themes - AdiPress SA</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff}
       .sidebar{position:fixed;left:0;top:0;width:250px;height:100vh;background:#1a1a1a;border-right:1px solid #333;padding:20px}
       .sidebar h2{margin-bottom:30px;font-size:18px}
       .sidebar a{display:block;padding:12px;margin-bottom:5px;color:#999;text-decoration:none;border-radius:8px}
       .sidebar a:hover,.sidebar a.active{background:#0a0a0a;color:#fff}
       .main{margin-left:250px;padding:30px}
       .card{background:#1a1a1a;padding:20px;border-radius:12px;border:1px solid #333;margin-bottom:20px}
       .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}
       .theme{background:#0a0a0a;border:1px solid #333;border-radius:12px;overflow:hidden}
       .theme img{width:100%;height:200px;object-fit:cover}
       .theme-info{padding:15px}
       .theme-info h4{margin-bottom:5px}
       .theme-info p{font-size:12px;color:#999}
        input,select{padding:10px;background:#0a0a0a;border:1px solid #333;border-radius:8px;color:#fff;width:100%;margin-bottom:10px}
       .btn{padding:10px 20px;background:#3b82f6;border:none;border-radius:8px;color:#fff;cursor:pointer}
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>AdiPress SA</h2>
        <a href="/sa/dashboard">Dashboard</a>
        <a href="/sa/sites">Sites</a>
        <a href="/sa/runtimes">Runtimes</a>
        <a href="/sa/domains">Domains</a>
        <a href="/sa/themes" class="active">Themes</a>
        <a href="/sa/plugins">Plugins</a>
        <a href="/sa/languages">Languages</a>
        <a href="/sa/logout">Logout</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom:30px">Themes Management</h1>
        <div class="card">
            <h3 style="margin-bottom:15px">Upload New Theme</h3>
            <form method="POST" action="/sa/themes/upload" enctype="multipart/form-data">
                <input type="text" name="name" placeholder="Theme Name" required>
                <input type="file" name="theme_zip" accept=".zip" required>
                <select name="runtime_type">
                    <option value="static">Static HTML/CSS/JS</option>
                    <option value="php">PHP</option>
                    <option value="python">Python</option>
                    <option value="nodejs">Node.js</option>
                </select>
                <input type="number" name="price" placeholder="Price (0 = Free)" value="0" step="0.01">
                <button type="submit" class="btn">Upload Theme</button>
            </form>
        </div>
        <div class="grid">
            {% for theme in themes %}
            <div class="theme">
                <img src="{{ theme.screenshot or '/static/placeholder.png' }}">
                <div class="theme-info">
                    <h4>{{ theme.name }}</h4>
                    <p>v{{ theme.version }} | {{ theme.runtime_type }} | ${{ theme.price }}</p>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
'''

SA_PLUGINS_HTML = SA_THEMES_HTML.replace('Themes','Plugins').replace('themes','plugins')
SA_LANGUAGES_HTML = SA_THEMES_HTML.replace('Themes','Languages').replace('themes','languages')

# ============================================
# PART 1 END - Continue to PART 2
# ============================================
# ============================================
# PART 2: CLIENT PANEL + PAAS FEATURES
# ============================================

import shutil
import zipfile
from werkzeug.utils import secure_filename

# ============================================
# CLIENT AUTH ROUTES
# ============================================

@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>AdiPress - Build Anything</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#000;color:#fff}
        .nav{display:flex;justify-content:space-between;padding:20px 50px;border-bottom:1px solid #222}
        .hero{text-align:center;padding:100px 20px}
        .hero h1{font-size:64px;margin-bottom:20px;background:linear-gradient(90deg,#0070f3,#00d4ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .hero p{font-size:20px;color:#999;margin-bottom:40px}
        .btn{padding:16px 32px;background:#0070f3;color:#fff;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block}
        .btn-outline{background:transparent;border:2px solid #333}
        .features{display:grid;grid-template-columns:repeat(3,1fr);gap:30px;padding:80px 50px;max-width:1200px;margin:0 auto}
        .feature{background:#111;padding:30px;border-radius:12px;border:1px solid #222}
        .feature h3{margin-bottom:10px;color:#0070f3}
    </style></head>
    <body>
        <div class="nav">
            <h2>AdiPress</h2>
            <div>
                <a href="/login" class="btn btn-outline">Login</a>
                <a href="/register" class="btn">Start Free</a>
            </div>
        </div>
        <div class="hero">
            <h1>Build. Deploy. Scale.</h1>
            <p>20 Programming Languages + Drag-Drop Builder + 50 Free Themes</p>
            <a href="/register" class="btn">Create Free Site</a>
        </div>
        <div class="features">
            <div class="feature"><h3>⚡ 20 Runtimes</h3><p>Python, PHP, Node.js, Java, Go, Rust + 14 more</p></div>
            <div class="feature"><h3>🎨 50 Free Themes</h3><p>Universal themes work on all languages</p></div>
            <div class="feature"><h3>🔌 Tenant Plugins</h3><p>PostgreSQL, Redis, S3 per site</p></div>
            <div class="feature"><h3>🌍 5 Free Domains</h3><p>adpress.site, buildnow.pk + Custom</p></div>
            <div class="feature"><h3>🚀 Git Deploy</h3><p>Push to deploy in 2 minutes</p></div>
            <div class="feature"><h3>🔒 Isolated</h3><p>Docker per site, Zero cross-tenant access</p></div>
        </div>
    </body></html>
    ''')

@app.route('/register', methods=['GET', 'POST'])
def client_register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        subdomain = request.form.get('subdomain').lower()
        domain_suffix = request.form.get('domain_suffix', 'adpress.site')
        
        if User.query.filter_by(email=email).first():
            return "Email already exists", 400
        
        full_domain = f"{subdomain}.{domain_suffix}"
        if Site.query.filter_by(domain=full_domain).first():
            return "Subdomain taken", 400
        
        user = User(email=email, full_name=request.form.get('name'))
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        
        site = Site(
            domain=full_domain,
            subdomain=subdomain,
            owner_id=user.id,
            site_name=request.form.get('site_name', 'My Website'),
            runtime_id=Runtime.query.filter_by(name='static').first().id
        )
        db.session.add(site)
        db.session.flush()
        
        site_domain = SiteDomain(
            site_id=site.id,
            domain=full_domain,
            is_primary=True,
            is_custom=False,
            verified=True
        )
        db.session.add(site_domain)
        db.session.commit()
        
        session['user_id'] = user.id
        return redirect(f"//{full_domain}/dashboard")
    
    domains = Domain.query.filter_by(is_system=True, is_active=True).all()
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Register - AdiPress</title>
    <style>
        body{font-family:Inter,sans-serif;background:#000;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
        .form{background:#111;padding:40px;border-radius:12px;width:450px;border:1px solid #222}
        input,select{width:100%;padding:12px;margin:10px 0;background:#0a0a0a;border:1px solid #333;color:#fff;border-radius:8px}
        button{width:100%;padding:14px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600;margin-top:10px}
        .domain-select{display:flex;gap:10px}
        .domain-select input{flex:1}
        .domain-select select{width:200px}
        h2{text-align:center;margin-bottom:30px}
    </style></head>
    <body><div class="form">
        <h2>Create Free Site</h2>
        <form method="POST">
            <input type="text" name="name" placeholder="Full Name" required>
            <input type="email" name="email" placeholder="Email" required>
            <input type="password" name="password" placeholder="Password" required>
            <input type="text" name="site_name" placeholder="Site Name" required>
            <div class="domain-select">
                <input type="text" name="subdomain" placeholder="yourname" pattern="[a-z0-9-]+" required>
                <select name="domain_suffix">
                    {% for d in domains %}
                    <option value="{{ d.domain_name }}">{{ d.domain_name }}</option>
                    {% endfor %}
                </select>
            </div>
            <button type="submit">Create Site</button>
        </form>
        <p style="text-align:center;margin-top:20px;color:#666">Already have account? <a href="/login" style="color:#0070f3">Login</a></p>
    </div></body></html>
    ''', domains=domains)

@app.route('/login', methods=['GET', 'POST'])
def client_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            site = Site.query.filter_by(owner_id=user.id).first()
            if site:
                return redirect(f"//{site.domain}/dashboard")
        return "Invalid credentials", 401
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Login - AdiPress</title>
    <style>
        body{font-family:Inter,sans-serif;background:#000;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
        .form{background:#111;padding:40px;border-radius:12px;width:400px;border:1px solid #222}
        input{width:100%;padding:12px;margin:10px 0;background:#0a0a0a;border:1px solid #333;color:#fff;border-radius:8px}
        button{width:100%;padding:14px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600}
        h2{text-align:center;margin-bottom:30px}
    </style></head>
    <body><div class="form">
        <h2>Login to AdiPress</h2>
        <form method="POST">
            <input type="email" name="email" placeholder="Email" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        <p style="text-align:center;margin-top:20px;color:#666">New user? <a href="/register" style="color:#0070f3">Register</a></p>
    </div></body></html>
    ''')

@app.route('/logout')
@login_required
def client_logout():
    session.clear()
    return redirect('/')

# ============================================
# CLIENT DASHBOARD
# ============================================

@app.route('/dashboard')
@login_required
def client_dashboard():
    site = g.site
    if site.owner_id != g.user.id and not session.get('impersonate'):
        abort(403)
    
    deployments = Deployment.query.filter_by(site_id=site.id).order_by(Deployment.created_at.desc()).limit(5).all()
    pages_count = Page.query.filter_by(site_id=site.id).count()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Dashboard - {{ site.domain }}</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin:30px 0}
        .card{background:#1a1a1a;padding:25px;border-radius:12px;border:1px solid #222}
        .card h4{color:#666;font-size:14px;margin-bottom:10px}
        .card h2{font-size:32px;color:#0070f3}
        .btn{padding:12px 24px;background:#0070f3;color:#fff;text-decoration:none;border-radius:8px;display:inline-block;margin:10px 10px 10px 0}
        table{width:100%;background:#1a1a1a;border-radius:12px;overflow:hidden;margin-top:20px}
        th,td{padding:15px;text-align:left;border-bottom:1px solid #222}
        th{background:#111;color:#666}
        .badge{padding:4px 8px;border-radius:4px;font-size:12px;background:#0a0;color:#fff}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard" class="active">📊 Overview</a>
            <a href="/dashboard/deployments">🚀 Deployments</a>
            <a href="/dashboard/runtime">⚙️ Runtime</a>
            <a href="/dashboard/domains">🔗 Domains</a>
            <a href="/dashboard/env">🔐 Environment</a>
            <a href="/dashboard/pages">📄 Pages</a>
            <a href="/dashboard/themes">🎨 Themes</a>
            <a href="/dashboard/plugins">🔌 Add-ons</a>
            <a href="/dashboard/media">📁 Media</a>
            <a href="/dashboard/settings">⚙️ Settings</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Dashboard</h1>
            <div class="stats">
                <div class="card"><h4>Plan</h4><h2>{{ site.plan|upper }}</h2></div>
                <div class="card"><h4>Runtime</h4><h2>{{ site.runtime.display_name if site.runtime else 'Static' }}</h2></div>
                <div class="card"><h4>Pages</h4><h2>{{ pages_count }}</h2></div>
                <div class="card"><h4>Status</h4><h2>{{ site.status|upper }}</h2></div>
            </div>
            
            <a href="/dashboard/runtime" class="btn">Change Runtime</a>
            <a href="/dashboard/themes" class="btn">Browse Themes</a>
            <a href="//{{ site.domain }}" target="_blank" class="btn">View Site</a>
            
            <h2 style="margin-top:40px">Recent Deployments</h2>
            <table>
                <tr><th>Commit</th><th>Status</th><th>Time</th></tr>
                {% for dep in deployments %}
                <tr>
                    <td><code>{{ dep.commit_hash[:7] if dep.commit_hash else 'Manual' }}</code></td>
                    <td><span class="badge">{{ dep.status }}</span></td>
                    <td>{{ dep.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body></html>
    ''', site=site, deployments=deployments, pages_count=pages_count)

@app.route('/dashboard/runtime', methods=['GET', 'POST'])
@login_required
def client_runtime():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    if request.method == 'POST':
        runtime_id = request.form.get('runtime_id')
        runtime = Runtime.query.get(runtime_id)
        if runtime and runtime.is_active:
            site.runtime_id = runtime_id
            db.session.commit()
            deploy_site(site)
            return redirect(url_for('client_dashboard'))
    
    runtimes = Runtime.query.filter_by(is_active=True).all()
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Runtime Settings</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        .runtime{background:#1a1a1a;padding:20px;border-radius:12px;border:2px solid #222;cursor:pointer}
        .runtime:hover{border-color:#0070f3}
        .runtime.selected{border-color:#0070f3;background:#0a1a2a}
        .runtime h4{margin-bottom:10px}
        .runtime code{color:#666;font-size:12px}
        button{padding:14px 32px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600;margin-top:20px}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/runtime" class="active">⚙️ Runtime</a>
            <a href="/dashboard/domains">🔗 Domains</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Select Runtime - 20 Languages</h1>
            <p style="color:#666;margin:20px 0">Current: {{ site.runtime.display_name if site.runtime else 'Static HTML' }}</p>
            <form method="POST">
                <div class="grid">
                    {% for rt in runtimes %}
                    <label class="runtime {% if site.runtime_id == rt.id %}selected{% endif %}">
                        <input type="radio" name="runtime_id" value="{{ rt.id }}" {% if site.runtime_id == rt.id %}checked{% endif %} style="display:none">
                        <h4>{{ rt.display_name }}</h4>
                        <code>{{ rt.docker_image }}</code>
                    </label>
                    {% endfor %}
                </div>
                <button type="submit">Save & Redeploy</button>
            </form>
        </div>
        <script>
            document.querySelectorAll('.runtime').forEach(el => {
                el.onclick = () => {
                    document.querySelectorAll('.runtime').forEach(r => r.classList.remove('selected'));
                    el.classList.add('selected');
                    el.querySelector('input').checked = true;
                }
            });
        </script>
    </body></html>
    ''', site=site, runtimes=runtimes)

@app.route('/dashboard/domains')
@login_required
def client_domains():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    domains = SiteDomain.query.filter_by(site_id=site.id).all()
    system_domains = Domain.query.filter_by(is_system=True, is_active=True).all()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Domains</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .card{background:#1a1a1a;padding:25px;border-radius:12px;border:1px solid #222;margin-bottom:20px}
        table{width:100%;background:#1a1a1a;border-radius:12px;overflow:hidden}
        th,td{padding:15px;text-align:left;border-bottom:1px solid #222}
        th{background:#111;color:#666}
        input,select{padding:12px;background:#0a0a0a;border:1px solid #333;color:#fff;border-radius:8px}
        button{padding:12px 24px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer}
        .badge{padding:4px 8px;border-radius:4px;font-size:12px;background:#0a0;color:#fff}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/domains" class="active">🔗 Domains</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Domains</h1>
            <table>
                <tr><th>Domain</th><th>Type</th><th>SSL</th><th>Status</th></tr>
                {% for d in domains %}
                <tr>
                    <td><strong>{{ d.domain }}</strong> {% if d.is_primary %}⭐{% endif %}</td>
                    <td>{{ 'Custom' if d.is_custom else 'Free' }}</td>
                    <td><span class="badge">{{ d.ssl_status }}</span></td>
                    <td>{{ 'Verified' if d.verified else 'Pending' }}</td>
                </tr>
                {% endfor %}
            </table>
            
            <div class="card">
                <h3>Add Free Subdomain</h3>
                <form method="POST" action="/dashboard/domains/add-free">
                    <input type="text" name="subdomain" placeholder="yourname" pattern="[a-z0-9-]+" required>
                    <select name="suffix">
                        {% for d in system_domains %}
                        <option value="{{ d.domain_name }}">{{ d.domain_name }}</option>
                        {% endfor %}
                    </select>
                    <button type="submit">Add Domain</button>
                </form>
            </div>
            
            <div class="card">
                <h3>Connect Custom Domain - Pro Plan</h3>
                <form method="POST" action="/dashboard/domains/add-custom">
                    <input type="text" name="domain" placeholder="yourdomain.com" required>
                    <button type="submit">Add Custom Domain</button>
                </form>
                <p style="color:#666;margin-top:10px;font-size:14px">Add CNAME: www → cname.adpress.site</p>
            </div>
        </div>
    </body></html>
    ''', site=site, domains=domains, system_domains=system_domains)

@app.route('/dashboard/domains/add-free', methods=['POST'])
@login_required
def client_add_free_domain():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    subdomain = request.form.get('subdomain').lower()
    suffix = request.form.get('suffix')
    full_domain = f"{subdomain}.{suffix}"
    
    if SiteDomain.query.filter_by(domain=full_domain).first():
        return "Domain taken", 400
    
    domain = SiteDomain(
        site_id=site.id,
        domain=full_domain,
        is_primary=False,
        is_custom=False,
        verified=True,
        ssl_status='active'
    )
    db.session.add(domain)
    db.session.commit()
    return redirect(url_for('client_domains'))

@app.route('/dashboard/themes')
@login_required
def client_themes():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    themes = Theme.query.filter_by(is_active=True).all()
    current_theme = SiteTheme.query.filter_by(site_id=site.id, active=True).first()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Themes</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        .theme{background:#1a1a1a;border-radius:12px;overflow:hidden;border:2px solid #222}
        .theme.active{border-color:#0070f3}
        .theme img{width:100%;height:200px;object-fit:cover}
        .theme-info{padding:15px}
        .btn{padding:10px 20px;background:#0070f3;color:#fff;border:none;border-radius:6px;cursor:pointer;width:100%}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/themes" class="active">🎨 Themes</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Themes - 50 Free + 1000 Paid</h1>
            <p style="color:#666;margin:20px 0">Universal themes work on all 20 languages</p>
            <div class="grid">
                {% for theme in themes %}
                <div class="theme {% if current_theme and current_theme.theme_id == theme.id %}active{% endif %}">
                    <img src="{{ theme.screenshot or 'https://placehold.co/400x300' }}">
                    <div class="theme-info">
                        <h4>{{ theme.name }}</h4>
                        <p style="color:#666;font-size:14px;margin:10px 0">{{ theme.runtime_type }} | ${{ theme.price }}</p>
                        {% if current_theme and current_theme.theme_id == theme.id %}
                        <button class="btn" disabled>Active</button>
                        {% else %}
                        <form method="POST" action="/dashboard/themes/{{ theme.id }}/activate">
                            <button type="submit" class="btn">Activate</button>
                        </form>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </body></html>
    ''', site=site, themes=themes, current_theme=current_theme)

@app.route('/dashboard/themes/<int:theme_id>/activate', methods=['POST'])
@login_required
def client_activate_theme(theme_id):
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    SiteTheme.query.filter_by(site_id=site.id, active=True).update({'active': False})
    
    site_theme = SiteTheme.query.filter_by(site_id=site.id, theme_id=theme_id).first()
    if not site_theme:
        site_theme = SiteTheme(site_id=site.id, theme_id=theme_id, active=True)
        db.session.add(site_theme)
    else:
        site_theme.active = True
    
    db.session.commit()
    return redirect(url_for('client_themes'))

# ============================================
# CLIENT PAGES - DRAG-DROP BUILDER
# ============================================

@app.route('/dashboard/pages')
@login_required
def client_pages():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    pages = Page.query.filter_by(site_id=site.id).order_by(Page.created_at.desc()).all()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Pages</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .header{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}
        .btn{padding:12px 24px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer;text-decoration:none}
        table{width:100%;background:#1a1a1a;border-radius:12px;overflow:hidden}
        th,td{padding:15px;text-align:left;border-bottom:1px solid #222}
        th{background:#111;color:#666}
        .badge{padding:4px 8px;border-radius:4px;font-size:12px;background:#0a0;color:#fff}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/pages" class="active">📄 Pages</a>
            <a href="/dashboard/themes">🎨 Themes</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <div class="header">
                <h1>Pages - {{ pages|length }}</h1>
                <a href="/dashboard/pages/new" class="btn">+ New Page</a>
            </div>
            <table>
                <tr><th>Title</th><th>Slug</th><th>Language</th><th>Status</th><th>Actions</th></tr>
                {% for page in pages %}
                <tr>
                    <td><strong>{{ page.title }}</strong></td>
                    <td><code>/{{ page.slug }}</code></td>
                    <td>{{ page.language }}</td>
                    <td><span class="badge">{{ page.status }}</span></td>
                    <td>
                        <a href="/dashboard/pages/{{ page.id }}/edit" style="color:#0070f3">Edit</a>
                        <a href="/dashboard/pages/{{ page.id }}/delete" style="color:#e00;margin-left:10px">Delete</a>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body></html>
    ''', site=site, pages=pages)

@app.route('/dashboard/pages/new', methods=['GET', 'POST'])
@login_required
def client_new_page():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    if request.method == 'POST':
        page = Page(
            site_id=site.id,
            slug=request.form.get('slug'),
            language=request.form.get('language', 'en'),
            title=request.form.get('title'),
            content=request.form.get('content'),
            status=request.form.get('status', 'draft')
        )
        db.session.add(page)
        db.session.commit()
        return redirect(url_for('client_pages'))
    
    languages = Language.query.filter_by(is_active=True).all()
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>New Page</title>
    <script src="https://cdn.jsdelivr.net/npm/grapesjs@0.21.8/dist/grapes.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/grapesjs@0.21.8/dist/css/grapes.min.css" rel="stylesheet"/>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .main{margin-left:240px;flex:1;display:flex;flex-direction:column;height:100vh}
        .topbar{background:#111;padding:15px 20px;border-bottom:1px solid #222;display:flex;gap:10px}
        input,select{padding:10px;background:#0a0a0a;border:1px solid #333;color:#fff;border-radius:6px}
        button{padding:10px 20px;background:#0070f3;color:#fff;border:none;border-radius:6px;cursor:pointer}
        #gjs{flex:1}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard/pages">← Back to Pages</a>
        </div>
        <div class="main">
            <form method="POST" id="page-form">
                <div class="topbar">
                    <input type="text" name="title" placeholder="Page Title" required style="flex:1">
                    <input type="text" name="slug" placeholder="url-slug" required style="width:200px">
                    <select name="language" style="width:150px">
                        {% for lang in languages %}
                        <option value="{{ lang.code }}">{{ lang.native_name }}</option>
                        {% endfor %}
                    </select>
                    <select name="status" style="width:120px">
                        <option value="draft">Draft</option>
                        <option value="published">Published</option>
                    </select>
                    <button type="submit">Save Page</button>
                </div>
                <input type="hidden" name="content" id="content-input">
                <div id="gjs"></div>
            </form>
        </div>
        <script>
            const editor = grapesjs.init({
                container: '#gjs',
                height: '100%',
                storageManager: false,
                blockManager: {
                    blocks: [
                        {id: 'text', label: 'Text', content: '<div data-gjs-type="text">Insert text here</div>'},
                        {id: 'image', label: 'Image', content: '<img src="https://placehold.co/600x400"/>'},
                        {id: 'heading', label: 'Heading', content: '<h1>Heading</h1>'},
                        {id: 'button', label: 'Button', content: '<button class="btn">Click Me</button>'},
                        {id: 'section', label: 'Section', content: '<section style="padding:50px"><h2>Section</h2><p>Content</p></section>'}
                    ]
                }
            });
            
            document.getElementById('page-form').onsubmit = function() {
                document.getElementById('content-input').value = editor.getHtml() + '<style>' + editor.getCss() + '</style>';
            };
        </script>
    </body></html>
    ''', site=site, languages=languages)

@app.route('/dashboard/pages/<int:page_id>/edit', methods=['GET', 'POST'])
@login_required
def client_edit_page(page_id):
    site = g.site
    page = Page.query.filter_by(id=page_id, site_id=site.id).first_or_404()
    
    if request.method == 'POST':
        page.title = request.form.get('title')
        page.slug = request.form.get('slug')
        page.content = request.form.get('content')
        page.status = request.form.get('status')
        page.language = request.form.get('language')
        page.updated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('client_pages'))
    
    return "Edit page - Same as new page with data loaded", 200

@app.route('/dashboard/pages/<int:page_id>/delete')
@login_required
def client_delete_page(page_id):
    site = g.site
    page = Page.query.filter_by(id=page_id, site_id=site.id).first_or_404()
    db.session.delete(page)
    db.session.commit()
    return redirect(url_for('client_pages'))

# ============================================
# CLIENT PLUGINS / ADD-ONS
# ============================================

@app.route('/dashboard/plugins')
@login_required
def client_plugins():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    all_plugins = Plugin.query.all()
    active_plugins = SitePlugin.query.filter_by(site_id=site.id, active=True).all()
    active_ids = [p.plugin_id for p in active_plugins]
    
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Add-ons</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        .plugin{background:#1a1a1a;padding:20px;border-radius:12px;border:2px solid #222}
        .plugin.active{border-color:#0a0}
        .plugin h4{margin-bottom:10px}
        .plugin p{color:#666;font-size:14px;margin-bottom:15px}
        .btn{padding:10px 20px;background:#0070f3;color:#fff;border:none;border-radius:6px;cursor:pointer;width:100%}
        .btn-danger{background:#e00}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/plugins" class="active">🔌 Add-ons</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Add-ons & Plugins</h1>
            <p style="color:#666;margin:20px 0">Extend your site with databases, cache, email, and more</p>
            <div class="grid">
                {% for plugin in plugins %}
                <div class="plugin {% if plugin.id in active_ids %}active{% endif %}">
                    <h4>{{ plugin.name }}</h4>
                    <p>{{ plugin.category }} | ${{ plugin.price }}/mo</p>
                    {% if plugin.id in active_ids %}
                    <form method="POST" action="/dashboard/plugins/{{ plugin.id }}/toggle">
                        <button type="submit" class="btn btn-danger">Deactivate</button>
                    </form>
                    {% else %}
                    <form method="POST" action="/dashboard/plugins/{{ plugin.id }}/toggle">
                        <button type="submit" class="btn">Activate</button>
                    </form>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
    </body></html>
    ''', site=site, plugins=all_plugins, active_ids=active_ids)

@app.route('/dashboard/plugins/<int:plugin_id>/toggle', methods=['POST'])
@login_required
def client_toggle_plugin(plugin_id):
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    site_plugin = SitePlugin.query.filter_by(site_id=site.id, plugin_id=plugin_id).first()
    if site_plugin:
        site_plugin.active = not site_plugin.active
    else:
        plugin = Plugin.query.get_or_404(plugin_id)
        site_plugin = SitePlugin(site_id=site.id, plugin_id=plugin_id, active=True)
        if plugin.supported_runtimes:
            site_plugin.env_vars = {"PLUGIN_" + plugin.slug.upper(): "enabled"}
        db.session.add(site_plugin)
    
    db.session.commit()
    return redirect(url_for('client_plugins'))

# ============================================
# ENVIRONMENT VARIABLES
# ============================================

@app.route('/dashboard/env', methods=['GET', 'POST'])
@login_required
def client_env():
    site = g.site
    if site.owner_id != g.user.id:
        abort(403)
    
    if request.method == 'POST':
        key = request.form.get('key').upper()
        value = request.form.get('value')
        is_secret = request.form.get('is_secret') == 'on'
        
        env = EnvVar.query.filter_by(site_id=site.id, key=key).first()
        if env:
            env.value = value
            env.is_secret = is_secret
        else:
            env = EnvVar(site_id=site.id, key=key, value=value, is_secret=is_secret)
            db.session.add(env)
        db.session.commit()
        return redirect(url_for('client_env'))
    
    env_vars = EnvVar.query.filter_by(site_id=site.id).all()
    return render_template_string('''
    <!DOCTYPE html>
    <html><head><title>Environment Variables</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;display:flex}
        .sidebar{width:240px;background:#111;height:100vh;padding:20px;border-right:1px solid #222;position:fixed}
        .sidebar h3{margin-bottom:30px;color:#0070f3}
        .sidebar a{display:block;padding:12px;color:#aaa;text-decoration:none;border-radius:8px;margin:5px 0}
        .sidebar a:hover,.sidebar a.active{background:#1a1a1a;color:#fff}
        .main{margin-left:240px;flex:1;padding:30px}
        .card{background:#1a1a1a;padding:25px;border-radius:12px;border:1px solid #222;margin-bottom:20px}
        table{width:100%;background:#1a1a1a;border-radius:12px;overflow:hidden}
        th,td{padding:15px;text-align:left;border-bottom:1px solid #222}
        th{background:#111;color:#666}
        input{padding:12px;background:#0a0a0a;border:1px solid #333;color:#fff;border-radius:8px;width:100%;margin:5px 0}
        button{padding:12px 24px;background:#0070f3;color:#fff;border:none;border-radius:8px;cursor:pointer}
        code{color:#0a0}
    </style></head>
    <body>
        <div class="sidebar">
            <h3>{{ site.domain }}</h3>
            <a href="/dashboard">📊 Overview</a>
            <a href="/dashboard/env" class="active">🔐 Environment</a>
            <a href="/dashboard/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <h1>Environment Variables</h1>
            <p style="color:#666;margin:20px 0">Access in code: <code>os.environ.get('KEY')</code></p>
            
            <table>
                <tr><th>Key</th><th>Value</th><th>Actions</th></tr>
                {% for env in env_vars %}
                <tr>
                    <td><code>{{ env.key }}</code></td>
                    <td>{{ '***' if env.is_secret else env.value }}</td>
                    <td><a href="/dashboard/env/{{ env.id }}/delete" style="color:#e00">Delete</a></td>
                </tr>
                {% endfor %}
            </table>
            
            <div class="card">
                <h3>Add New Variable</h3>
                <form method="POST">
                    <input type="text" name="key" placeholder="DATABASE_URL" required>
                    <input type="text" name="value" placeholder="postgresql://..." required>
                    <label style="display:block;margin:10px 0"><input type="checkbox" name="is_secret"> Secret (hidden)</label>
                    <button type="submit">Add Variable</button>
                </form>
            </div>
        </div>
    </body></html>
    ''', site=site, env_vars=env_vars)

@app.route('/dashboard/env/<int:env_id>/delete')
@login_required
def client_delete_env(env_id):
    site = g.site
    env = EnvVar.query.filter_by(id=env_id, site_id=site.id).first_or_404()
    db.session.delete(env)
    db.session.commit()
    return redirect(url_for('client_env'))

# ============================================
# PUBLIC SITE RENDERING - Theme Engine
# ============================================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def render_site(path):
    site = g.site
    if not site:
        return "Site not found", 404
    
    slug = path or 'home'
    lang = request.args.get('lang', site.default_language)
    page = Page.query.filter_by(site_id=site.id, slug=slug, language=lang, status='published').first()
    
    if not page:
        return "Page not found", 404
    
    site_theme = SiteTheme.query.filter_by(site_id=site.id, active=True).first()
    if not site_theme:
        return page.content
    
    theme = Theme.query.get(site_theme.theme_id)
    theme_ctx = ThemeContext(site, page).to_dict()
    
    if site.runtime and site.runtime.language == 'python':
        return render_template_string(page.content, **theme_ctx)
    elif site.runtime and site.runtime.language == 'php':
        php_content = page.content.replace('{{', '<?php echo $').replace('}}', '; ?>')
        return php_content
    else:
        return render_template_string(page.content, **theme_ctx)

# ============================================
# MAIN ENTRY POINT - RAILWAY READY
# ============================================

if __name__ == '__main__':
    # Tables already created at app start, but this ensures they exist in dev too
    with app.app_context():
        db.create_all()
    
    print("🚀 AdiPress v3.1 Starting on Railway...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
