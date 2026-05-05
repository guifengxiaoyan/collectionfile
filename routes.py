import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from models import db, Admin, Collector, Announcement, AnnouncementAttachment, CollectionTheme, CollectionObject, Attachment, ThemeAttachment, ThemeObject, beijing_now, collector_login_manager
from config import Config
from utils import (
    allowed_file, get_theme_folder, get_object_folder, get_announcement_folder,
    rename_uploaded_file, create_export_archive
)
import openpyxl

def register_routes(app):
    
    @app.template_filter('time_remaining')
    def time_remaining(deadline):
        now = beijing_now()
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=now.tzinfo)
        if deadline < now:
            return '已截止'
        delta = deadline - now
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        if days > 0:
            return f'{days}天{hours}小时'
        elif hours > 0:
            return f'{hours}小时{minutes}分钟'
        else:
            return f'{minutes}分钟'

    @app.template_filter('time_progress')
    def time_progress(deadline, created_at):
        now = beijing_now()
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=now.tzinfo)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=now.tzinfo)
        if deadline < now:
            return 0
        total = (deadline - created_at).total_seconds()
        if total <= 0:
            return 0
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            return 0
        progress = (remaining / total) * 100
        return max(0, min(100, int(progress)))

    @app.context_processor
    def inject_now():
        return {'now': beijing_now()}

    def collector_login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'collector_id' not in session:
                return redirect(url_for('collector_login', next=request.url))
            return f(*args, **kwargs)
        return decorated_function

    @app.context_processor
    def inject_collector():
        collector = None
        if 'collector_id' in session:
            collector = Collector.query.get(session['collector_id'])
        return {'current_collector': collector}

    @app.route('/')
    def index():
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
        now = beijing_now()
        expired_themes = CollectionTheme.query.filter(
            CollectionTheme.is_active == True,
            CollectionTheme.deadline < now
        ).all()
        for theme in expired_themes:
            theme.is_active = False
        if expired_themes:
            db.session.commit()
        
        if 'collector_id' in session:
            collector = Collector.query.get(session['collector_id'])
            if collector and collector.collection_object:
                obj = collector.collection_object
                themes = CollectionTheme.query.filter(
                    CollectionTheme.is_active == True,
                    CollectionTheme.id.in_(
                        db.session.query(ThemeObject.theme_id).filter_by(object_id=obj.id)
                    )
                ).order_by(CollectionTheme.deadline.asc()).all()
                return render_template('index.html', announcements=announcements, themes=themes, collector=collector, my_object=obj)
        
        themes = CollectionTheme.query.filter_by(is_active=True).order_by(CollectionTheme.deadline.asc()).all()
        return render_template('index.html', announcements=announcements, themes=themes)

    @app.route('/collector/login', methods=['GET', 'POST'])
    def collector_login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            collector = Collector.query.filter_by(username=username).first()
            if collector and collector.check_password(password):
                session['collector_id'] = collector.id
                next_url = request.args.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect(url_for('index'))
            flash('用户名或密码错误', 'error')
        return render_template('collector_login.html')

    @app.route('/collector/logout')
    def collector_logout():
        session.pop('collector_id', None)
        return redirect(url_for('index'))

    @app.route('/theme/<int:theme_id>')
    @collector_login_required
    def theme_detail(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        collector = Collector.query.get(session['collector_id'])
        obj = collector.collection_object if collector else None
        
        if obj:
            theme_obj = ThemeObject.query.filter_by(theme_id=theme_id, object_id=obj.id).first()
            if not theme_obj:
                flash('您无权访问此主题', 'error')
                return redirect(url_for('index'))
            
            attachments = Attachment.query.filter_by(collection_object_id=obj.id).all()
            is_completed = len(attachments) > 0
            return render_template('theme_detail.html', theme=theme, collection_object=obj, 
                                 attachments=attachments, is_completed=is_completed)
        
        objects = CollectionTheme.query.get(theme_id).objects
        return render_template('theme_detail.html', theme=theme, objects=objects)

    @app.route('/upload/<int:object_id>', methods=['GET', 'POST'])
    @collector_login_required
    def upload_page(object_id):
        collection_object = CollectionObject.query.get_or_404(object_id)
        collector = Collector.query.get(session['collector_id'])
        
        if collector and collection_object.collector_id != collector.id:
            flash('您无权上传到此对象', 'error')
            return redirect(url_for('index'))
        
        theme_link = ThemeObject.query.filter_by(object_id=object_id).first()
        theme = theme_link.theme if theme_link else None
        
        if not theme:
            flash('该对象未关联主题', 'error')
            return redirect(url_for('index'))
        
        now = beijing_now()
        deadline = theme.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=now.tzinfo)
        is_expired = deadline < now
        
        if is_expired:
            if request.method == 'POST':
                flash('该主题已超过截止时间，无法上传附件', 'error')
                return redirect(url_for('index'))
            return render_template('upload.html', theme=theme, collection_object=collection_object, expired=True)
        
        if request.method == 'POST':
            if 'finish' in request.form:
                attachments = Attachment.query.filter_by(collection_object_id=object_id).all()
                if len(attachments) == 0:
                    flash('请先上传附件后再完成', 'error')
                    return redirect(url_for('upload_page', object_id=object_id))
                
                for to in ThemeObject.query.filter_by(object_id=object_id).all():
                    to.is_completed = True
                    to.completed_at = beijing_now()
                db.session.commit()
                return redirect(url_for('index'))
            
            if 'file' in request.files:
                files = request.files.getlist('file')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, Config.ALLOWED_EXTENSIONS):
                        filename = secure_filename(file.filename)
                        stored_name = rename_uploaded_file(theme.id, collection_object.id, filename, filename)
                        folder = get_object_folder(theme.id, collection_object.id)
                        file_path = os.path.join(folder, stored_name)
                        file.save(file_path)
                        
                        attachment = Attachment(
                            filename=stored_name,
                            original_name=filename,
                            collection_object_id=collection_object.id
                        )
                        db.session.add(attachment)
                
                db.session.commit()
                return redirect(url_for('upload_page', object_id=object_id))
        
        attachments = Attachment.query.filter_by(collection_object_id=object_id).all()
        return render_template('upload.html', collection_object=collection_object, theme=theme, attachments=attachments)

    @app.route('/download/attachment/<int:attachment_id>')
    @collector_login_required
    def download_attachment(attachment_id):
        attachment = Attachment.query.get_or_404(attachment_id)
        obj = attachment.collection_object
        collector = Collector.query.get(session['collector_id'])
        if obj.collector_id != collector.id:
            flash('无权下载', 'error')
            return redirect(url_for('index'))
        file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), attachment.filename)
        return send_file(file_path, as_attachment=True, download_name=attachment.original_name)

    @app.route('/announcement/download/<int:attachment_id>')
    def download_announcement_attachment(attachment_id):
        attachment = AnnouncementAttachment.query.get_or_404(attachment_id)
        file_path = os.path.join(get_announcement_folder(), attachment.filename)
        return send_file(file_path, as_attachment=True, download_name=attachment.original_name)

    @app.route('/theme/download/<int:attachment_id>')
    def download_theme_attachment(attachment_id):
        attachment = ThemeAttachment.query.get_or_404(attachment_id)
        file_path = os.path.join(get_theme_folder(attachment.theme_id), attachment.filename)
        return send_file(file_path, as_attachment=True, download_name=attachment.original_name)

    @app.route('/upload/delete-attachment/<int:attachment_id>', methods=['POST'])
    @collector_login_required
    def delete_upload_attachment(attachment_id):
        attachment = Attachment.query.get_or_404(attachment_id)
        obj = attachment.collection_object
        collector = Collector.query.get(session['collector_id'])
        if obj.collector_id != collector.id:
            return jsonify({'success': False, 'error': '无权删除'}), 403
        file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(attachment)
        db.session.commit()
        return jsonify({'success': True})

    @app.route('/admin/theme/attachment/<int:attachment_id>/delete', methods=['GET', 'POST'])
    @login_required
    def delete_theme_attachment(attachment_id):
        attachment = ThemeAttachment.query.get_or_404(attachment_id)
        theme_id = attachment.theme_id
        file_path = os.path.join(get_theme_folder(theme_id), attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(attachment)
        db.session.commit()
        flash('附件已删除', 'success')
        return redirect(url_for('edit_theme', theme_id=theme_id))

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            admin = Admin.query.filter_by(username=username).first()
            if admin and check_password_hash(admin.password_hash, password):
                login_user(admin)
                return redirect(url_for('admin_dashboard'))
            flash('用户名或密码错误', 'error')
        return render_template('admin_login.html')

    @app.route('/admin/logout')
    @login_required
    def admin_logout():
        logout_user()
        return redirect(url_for('index'))

    @app.route('/admin')
    @login_required
    def admin_dashboard():
        now = beijing_now()
        expired_themes = CollectionTheme.query.filter(
            CollectionTheme.is_active == True,
            CollectionTheme.deadline < now
        ).all()
        for theme in expired_themes:
            theme.is_active = False
        if expired_themes:
            db.session.commit()
        
        active_themes = CollectionTheme.query.filter_by(is_active=True).order_by(CollectionTheme.deadline.asc()).all()
        archived_themes = CollectionTheme.query.filter_by(is_active=False).order_by(CollectionTheme.created_at.desc()).all()
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
        return render_template('admin_dashboard.html', active_themes=active_themes, archived_themes=archived_themes, announcements=announcements)

    @app.route('/admin/change-password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not current_user.check_password(old_password):
                flash('原密码错误', 'error')
                return redirect(url_for('change_password'))
            
            if new_password != confirm_password:
                flash('新密码与确认密码不一致', 'error')
                return redirect(url_for('change_password'))
            
            if len(new_password) < 6:
                flash('新密码长度不能少于6位', 'error')
                return redirect(url_for('change_password'))
            
            current_user.set_password(new_password)
            db.session.commit()
            flash('密码修改成功', 'success')
            return redirect(url_for('admin_dashboard'))
        
        return render_template('change_password.html')

    @app.route('/admin/theme/create', methods=['GET', 'POST'])
    @login_required
    def create_theme():
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            announcement = request.form.get('announcement')
            deadline = request.form.get('deadline')
            collector_name = request.form.get('collector_name')
            
            theme = CollectionTheme(
                title=title,
                description=description,
                announcement=announcement,
                deadline=datetime.strptime(deadline, '%Y-%m-%dT%H:%M'),
                collector_name=collector_name
            )
            db.session.add(theme)
            db.session.commit()
            
            if 'attachments' in request.files:
                import json
                removed_files = []
                if request.form.get('removed_files'):
                    try:
                        removed_files = json.loads(request.form.get('removed_files'))
                    except:
                        removed_files = []
                
                files = request.files.getlist('attachments')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, Config.ALLOWED_EXTENSIONS):
                        if file.filename in removed_files:
                            continue
                        original_name = file.filename
                        filename = secure_filename(original_name)
                        folder = get_theme_folder(theme.id)
                        counter = 1
                        while os.path.exists(os.path.join(folder, filename)):
                            name, ext = os.path.splitext(original_name)
                            filename = f"{name}_{counter}{ext}"
                            counter += 1
                        file_path = os.path.join(folder, filename)
                        file.save(file_path)
                        
                        att = ThemeAttachment(
                            filename=filename,
                            original_name=original_name,
                            theme_id=theme.id
                        )
                        db.session.add(att)
            db.session.commit()
            
            flash('收集主题创建成功', 'success')
            return redirect(url_for('admin_dashboard'))
        return render_template('theme_create.html')

    @app.route('/admin/objects')
    @login_required
    def admin_objects():
        objects = CollectionObject.query.all()
        return render_template('admin_objects.html', objects=objects)

    @app.route('/admin/object/create', methods=['GET', 'POST'])
    @login_required
    def admin_create_object():
        if request.method == 'POST':
            name = request.form.get('name')
            collector_username = request.form.get('collector_username')
            collector_password = request.form.get('collector_password')
            theme_ids = request.form.getlist('theme_ids')
            
            existing = CollectionObject.query.filter_by(name=name).first()
            if existing:
                flash('收集对象名称已存在', 'error')
                return redirect(url_for('admin_create_object'))
            
            collector = Collector.query.filter_by(username=collector_username).first()
            if collector:
                flash('收集者用户名已存在', 'error')
                return redirect(url_for('admin_create_object'))
            
            collector = Collector(username=collector_username)
            collector.set_password(collector_password)
            db.session.add(collector)
            db.session.flush()
            
            obj = CollectionObject(name=name, collector_id=collector.id)
            db.session.add(obj)
            db.session.flush()
            
            for tid in theme_ids:
                if tid:
                    theme_obj = ThemeObject(theme_id=int(tid), object_id=obj.id)
                    db.session.add(theme_obj)
            
            db.session.commit()
            flash(f'收集对象和账号创建成功，用户名: {collector_username}', 'success')
            return redirect(url_for('admin_objects'))
        
        themes = CollectionTheme.query.filter_by(is_active=True).all()
        return render_template('admin_object_create.html', themes=themes)

    @app.route('/admin/object/<int:object_id>/edit', methods=['GET', 'POST'])
    @login_required
    def admin_edit_object(object_id):
        obj = CollectionObject.query.get_or_404(object_id)
        collector = obj.collector
        
        if request.method == 'POST':
            obj.name = request.form.get('name')
            theme_ids = request.form.getlist('theme_ids')
            
            ThemeObject.query.filter_by(object_id=object_id).delete()
            for tid in theme_ids:
                if tid:
                    theme_obj = ThemeObject(theme_id=int(tid), object_id=object_id)
                    db.session.add(theme_obj)
            
            if request.form.get('reset_password'):
                new_password = request.form.get('new_password')
                if new_password and len(new_password) >= 6:
                    collector.set_password(new_password)
            
            db.session.commit()
            flash('收集对象已更新', 'success')
            return redirect(url_for('admin_objects'))
        
        themes = CollectionTheme.query.filter_by(is_active=True).all()
        return render_template('admin_object_edit.html', obj=obj, collector=collector, themes=themes)

    @app.route('/admin/object/<int:object_id>/reset-password', methods=['GET', 'POST'])
    @login_required
    def admin_collector_reset_password(object_id):
        obj = CollectionObject.query.get_or_404(object_id)
        collector = obj.collector
        
        if not collector:
            flash('该对象没有关联的收集者账号', 'error')
            return redirect(url_for('admin_objects'))
        
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            if len(new_password) < 6:
                flash('密码长度不能少于6位', 'error')
                return redirect(url_for('admin_collector_reset_password', object_id=object_id))
            
            collector.set_password(new_password)
            db.session.commit()
            flash(f'密码已重置，用户名: {collector.username}，新密码: {new_password}', 'success')
            return redirect(url_for('admin_objects'))
        
        return render_template('admin_collector_reset_password.html', collector=collector, obj=obj)

    @app.route('/admin/theme/<int:theme_id>/objects', methods=['GET', 'POST'])
    @login_required
    def manage_theme_objects(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        
        if request.method == 'POST':
            if 'add_object' in request.form:
                name = request.form.get('object_name')
                obj = CollectionObject(name=name)
                db.session.add(obj)
                db.session.flush()
                
                theme_obj = ThemeObject(theme_id=theme_id, object_id=obj.id)
                db.session.add(theme_obj)
                db.session.commit()
                flash('收集对象添加成功', 'success')
            
            elif 'import_excel' in request.form:
                if 'excel_file' in request.files:
                    file = request.files.get('excel_file')
                    if file and file.filename.endswith(('.xls', '.xlsx')):
                        wb = openpyxl.load_workbook(file)
                        ws = wb.active
                        imported_count = 0
                        for row in ws.iter_rows(values_only=True):
                            if row and len(row) > 0:
                                cell = row[0]
                                if cell is not None:
                                    name = str(cell).strip()
                                    if name:
                                        existing = CollectionObject.query.filter_by(name=name).first()
                                        if not existing:
                                            obj = CollectionObject(name=name)
                                            db.session.add(obj)
                                            db.session.flush()
                                            theme_obj = ThemeObject(theme_id=theme_id, object_id=obj.id)
                                            db.session.add(theme_obj)
                                            imported_count += 1
                        db.session.commit()
                        flash(f'Excel导入成功，共导入 {imported_count} 条数据', 'success')
        
        objects = theme.objects
        return render_template('theme_objects.html', theme=theme, objects=objects)

    @app.route('/admin/theme/<int:theme_id>/delete', methods=['POST'])
    @login_required
    def delete_theme(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        theme_folder = get_theme_folder(theme_id)
        if os.path.exists(theme_folder):
            import shutil
            shutil.rmtree(theme_folder)
        db.session.delete(theme)
        db.session.commit()
        flash('主题已删除', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/object/<int:object_id>/delete', methods=['POST'])
    @login_required
    def delete_object(object_id):
        obj = CollectionObject.query.get_or_404(object_id)
        if obj.collector:
            db.session.delete(obj.collector)
        db.session.delete(obj)
        db.session.commit()
        flash('收集对象已删除', 'success')
        return redirect(url_for('admin_objects'))

    @app.route('/admin/object/<int:object_id>/reset', methods=['POST'])
    @login_required
    def reset_object_upload(object_id):
        obj = CollectionObject.query.get_or_404(object_id)
        attachments = Attachment.query.filter_by(collection_object_id=object_id).all()
        for att in attachments:
            file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), att.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            db.session.delete(att)
        for to in ThemeObject.query.filter_by(object_id=object_id).all():
            to.is_completed = False
            to.completed_at = None
        db.session.commit()
        flash('上传已重置，可以重新上传', 'success')
        return redirect(url_for('admin_objects'))

    @app.route('/admin/attachment/<int:attachment_id>/delete', methods=['POST'])
    @login_required
    def delete_attachment(attachment_id):
        att = Attachment.query.get_or_404(attachment_id)
        obj = att.collection_object
        file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), att.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(att)
        db.session.commit()
        flash('附件已删除', 'success')
        return redirect(url_for('admin_objects'))

    @app.route('/admin/object/<int:object_id>/download-attachments')
    @login_required
    def download_object_attachments(object_id):
        obj = CollectionObject.query.get_or_404(object_id)
        attachments = Attachment.query.filter_by(collection_object_id=object_id).all()
        if not attachments:
            flash('该对象没有附件', 'error')
            return redirect(url_for('admin_objects'))
        
        if len(attachments) == 1:
            att = attachments[0]
            file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), att.filename)
            ext = os.path.splitext(att.original_name)[1]
            download_name = f"{obj.name}{ext}"
            return send_file(file_path, as_attachment=True, download_name=download_name)
        else:
            import io
            import zipfile
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for att in attachments:
                    file_path = os.path.join(get_object_folder(obj.theme_links.first().theme_id if obj.theme_links.first() else 0, obj.id), att.filename)
                    if os.path.exists(file_path):
                        zf.write(file_path, f"{obj.name}_{att.original_name}")
            memory_file.seek(0)
            return send_file(memory_file, as_attachment=True, download_name=f"{obj.name}_附件.zip")

    @app.route('/admin/theme/<int:theme_id>/export')
    @login_required
    def export_theme_attachments(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        archive_name = create_export_archive(theme_id, theme.title)
        archive_path = os.path.join(get_theme_folder(theme_id), archive_name)
        return send_file(archive_path, as_attachment=True)

    @app.route('/admin/announcement/create', methods=['GET', 'POST'])
    @login_required
    def create_announcement():
        if request.method == 'POST':
            title = request.form.get('title')
            content = request.form.get('content')
            
            announcement = Announcement(title=title, content=content)
            db.session.add(announcement)
            db.session.commit()
            
            if 'attachments' in request.files:
                import json
                removed_files = []
                if request.form.get('removed_files'):
                    try:
                        removed_files = json.loads(request.form.get('removed_files'))
                    except:
                        removed_files = []
                
                files = request.files.getlist('attachments')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, Config.ALLOWED_EXTENSIONS):
                        if file.filename in removed_files:
                            continue
                        original_name = file.filename
                        filename = secure_filename(original_name)
                        folder = get_announcement_folder()
                        counter = 1
                        while os.path.exists(os.path.join(folder, filename)):
                            name, ext = os.path.splitext(original_name)
                            filename = f"{name}_{counter}{ext}"
                            counter += 1
                        file_path = os.path.join(folder, filename)
                        file.save(file_path)
                        
                        att = AnnouncementAttachment(
                            filename=filename,
                            original_name=original_name,
                            announcement_id=announcement.id
                        )
                        db.session.add(att)
            
            db.session.commit()
            flash('公告创建成功', 'success')
            return redirect(url_for('admin_dashboard'))
        return render_template('announcement_create.html')

    @app.route('/admin/announcement/<int:announcement_id>/delete', methods=['POST'])
    @login_required
    def delete_announcement(announcement_id):
        announcement = Announcement.query.get_or_404(announcement_id)
        for att in announcement.attachments:
            file_path = os.path.join(get_announcement_folder(), att.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        db.session.delete(announcement)
        db.session.commit()
        flash('公告已删除', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/announcement/<int:announcement_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_announcement(announcement_id):
        announcement = Announcement.query.get_or_404(announcement_id)
        if request.method == 'POST':
            announcement.title = request.form.get('title')
            announcement.content = request.form.get('content')
            db.session.commit()
            
            if 'attachments' in request.files:
                import json
                removed_files = []
                if request.form.get('removed_files'):
                    try:
                        removed_files = json.loads(request.form.get('removed_files'))
                    except:
                        removed_files = []
                
                files = request.files.getlist('attachments')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, Config.ALLOWED_EXTENSIONS):
                        if file.filename in removed_files:
                            continue
                        original_name = file.filename
                        filename = secure_filename(original_name)
                        folder = get_announcement_folder()
                        counter = 1
                        while os.path.exists(os.path.join(folder, filename)):
                            name, ext = os.path.splitext(original_name)
                            filename = f"{name}_{counter}{ext}"
                            counter += 1
                        file_path = os.path.join(folder, filename)
                        file.save(file_path)
                        
                        att = AnnouncementAttachment(
                            filename=filename,
                            original_name=original_name,
                            announcement_id=announcement.id
                        )
                        db.session.add(att)
            db.session.commit()
            flash('公告已更新', 'success')
            return redirect(url_for('admin_dashboard'))
        return render_template('announcement_edit.html', announcement=announcement)

    @app.route('/admin/announcement/attachment/<int:attachment_id>/delete', methods=['GET', 'POST'])
    @login_required
    def delete_announcement_attachment(attachment_id):
        attachment = AnnouncementAttachment.query.get_or_404(attachment_id)
        announcement_id = attachment.announcement_id
        file_path = os.path.join(get_announcement_folder(), attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(attachment)
        db.session.commit()
        flash('附件已删除', 'success')
        return redirect(url_for('edit_announcement', announcement_id=announcement_id))

    @app.route('/admin/theme/<int:theme_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_theme(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        if request.method == 'POST':
            theme.title = request.form.get('title')
            theme.description = request.form.get('description')
            theme.announcement = request.form.get('announcement')
            theme.deadline = datetime.strptime(request.form.get('deadline'), '%Y-%m-%dT%H:%M')
            theme.collector_name = request.form.get('collector_name')
            
            if 'attachments' in request.files:
                files = request.files.getlist('attachments')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, Config.ALLOWED_EXTENSIONS):
                        original_name = file.filename
                        filename = secure_filename(original_name)
                        folder = get_theme_folder(theme.id)
                        counter = 1
                        while os.path.exists(os.path.join(folder, filename)):
                            name, ext = os.path.splitext(original_name)
                            filename = f"{name}_{counter}{ext}"
                            counter += 1
                        file_path = os.path.join(folder, filename)
                        file.save(file_path)
                        
                        att = ThemeAttachment(
                            filename=filename,
                            original_name=original_name,
                            theme_id=theme.id
                        )
                        db.session.add(att)
            
            db.session.commit()
            flash('主题已更新', 'success')
            return redirect(url_for('admin_dashboard'))
        return render_template('theme_edit.html', theme=theme)

    @app.route('/admin/theme/<int:theme_id>/toggle', methods=['POST'])
    @login_required
    def toggle_theme_status(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        theme.is_active = not theme.is_active
        db.session.commit()
        return jsonify({'success': True, 'is_active': theme.is_active})

    @app.route('/admin/theme/<int:theme_id>/archive', methods=['POST'])
    @login_required
    def archive_theme(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        theme.is_active = False
        db.session.commit()
        flash('主题已归档', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/theme/<int:theme_id>/restore', methods=['POST'])
    @login_required
    def restore_theme(theme_id):
        theme = CollectionTheme.query.get_or_404(theme_id)
        theme.is_active = True
        db.session.commit()
        flash('主题已恢复', 'success')
        return redirect(url_for('manage_theme_objects', theme_id=theme_id))

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404
