def can_user_review(user, target):
    """
    Decoupled service method to check if a user is eligible to review
    the target Product or Service.
    Currently, returns True for any authenticated user.
    """
    if not user or not user.is_authenticated:
        return False
    return True
