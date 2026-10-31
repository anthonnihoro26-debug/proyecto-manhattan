from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("asistencias", "0016_profesor_sexo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ReporteEnvio",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("semana_inicio", models.DateField(unique=True)),
                ("iniciado_en", models.DateTimeField(auto_now_add=True)),
                ("finalizado_en", models.DateTimeField(blank=True, null=True)),
                ("estado", models.CharField(choices=[("iniciado", "En proceso"), ("completado", "Completado"), ("parcial", "Parcial"), ("error", "Revisar error")], default="iniciado", max_length=12)),
                ("origen", models.CharField(default="manual", max_length=20)),
                ("enviados", models.PositiveIntegerField(default=0)),
                ("errores", models.PositiveIntegerField(default=0)),
                ("resumen", models.TextField(blank=True, default="")),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-iniciado_en"], "verbose_name": "Envío semanal", "verbose_name_plural": "Envíos semanales"},
        ),
    ]
