from core.labs.models.visual_models import VisualModel


def list_models():
    return VisualModel.objects.all()
