def user_role_context(request):
    if not request.user.is_authenticated:
        return {
            'is_council': False,
            'is_board': False,
            'is_minister': False,
            'is_chairman': False,
            'is_sec_general': False,
            'is_institution': False,
            'is_reviewer': False,
            'user_role_label': '',
            'user_role_code': '',
            'unread_notifications_count': 0,
            'recent_notifications': [],
            'is_approved_user': False,
        }
    user = request.user
    unread_count = user.notifications.filter(is_read=False).count() if hasattr(user, 'notifications') else 0
    recent_notifs = user.notifications.all()[:5] if hasattr(user, 'notifications') else []
    return {
        'is_council': user.is_council,
        'is_board': user.is_board,
        'is_minister': user.is_minister,
        'is_chairman': getattr(user, 'is_chairman', False),
        'is_sec_general': getattr(user, 'is_sec_general', False),
        'is_institution': user.is_institution_rep,
        'is_reviewer': user.is_reviewer,
        'user_role_label': user.get_role_display(),
        'user_role_code': user.role,
        'unread_notifications_count': unread_count,
        'recent_notifications': recent_notifs,
        'is_approved_user': user.is_approved,
    }
