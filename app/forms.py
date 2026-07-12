"""Formulários e validações do site."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired

from wtforms import (
    BooleanField,
    EmailField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)

from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    NumberRange,
    Optional,
    URL,
)

PARTICIPATION_CHOICES = [
    ("barbeiro", "Barbeiro(a)"),
    ("trancista", "Trancista"),
    ("artista", "Artista / expositor(a)"),
    ("oficineiro", "Oficineiro(a) / educador(a)"),
    ("atleta", "Atleta / demonstração esportiva"),
    ("empreendedor", "Empreendedor(a) / alimentação"),
    ("voluntario", "Voluntário(a)"),
    ("outro", "Outra participação"),
]


class RegistrationForm(FlaskForm):
    full_name = StringField(
        "Nome completo", validators=[DataRequired(), Length(min=3, max=140)]
    )
    social_name = StringField(
        "Nome social ou artístico", validators=[Optional(), Length(max=140)]
    )
    email = EmailField("E-mail", validators=[DataRequired(), Email(), Length(max=180)])
    phone = StringField("WhatsApp", validators=[DataRequired(), Length(min=8, max=30)])
    neighborhood = StringField("Bairro", validators=[DataRequired(), Length(max=100)])
    city = StringField(
        "Cidade", validators=[DataRequired(), Length(max=100)], default="Belo Horizonte"
    )
    participation_type = SelectField(
        "Como deseja participar?",
        choices=PARTICIPATION_CHOICES,
        validators=[DataRequired()],
    )
    experience = TextAreaField(
        "Conte sobre sua experiência e proposta",
        validators=[DataRequired(), Length(min=20, max=1800)],
    )
    instagram = StringField("Instagram", validators=[Optional(), Length(max=120)])
    portfolio_url = StringField(
        "Link de portfólio ou trabalho", validators=[Optional(), URL(), Length(max=300)]
    )
    equipment_needed = TextAreaField(
        "Estrutura ou equipamento necessário", validators=[Optional(), Length(max=800)]
    )
    accessibility_needs = TextAreaField(
        "Necessidades de acessibilidade", validators=[Optional(), Length(max=800)]
    )
    availability = SelectField(
        "Disponibilidade no dia",
        choices=[
            ("integral", "Período integral"),
            ("manha", "Manhã"),
            ("tarde", "Tarde"),
            ("combinar", "A combinar"),
        ],
        validators=[DataRequired()],
    )
    lgpd_consent = BooleanField(
        "Autorizo o uso destes dados para organização e contato sobre o evento.",
        validators=[DataRequired()],
    )
    submit = SubmitField("Enviar inscrição")


class AdminLoginForm(FlaskForm):
    password = PasswordField("Senha administrativa", validators=[DataRequired()])
    submit = SubmitField("Entrar")


class GalleryImageForm(FlaskForm):
    """Formulário administrativo para inserir fotos na galeria."""

    image = FileField(
        "Imagem",
        validators=[
            FileRequired(),
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                "Use JPG, PNG ou WebP.",
            ),
        ],
    )

    title = StringField(
        "Título",
        validators=[
            DataRequired(),
            Length(max=120),
        ],
    )

    description = TextAreaField(
        "Descrição",
        validators=[
            Optional(),
            Length(max=300),
        ],
    )

    alt_text = StringField(
        "Texto alternativo",
        validators=[
            DataRequired(),
            Length(max=180),
        ],
    )

    display_order = IntegerField(
        "Ordem de exibição",
        default=0,
        validators=[
            DataRequired(),
            NumberRange(min=0, max=9999),
        ],
    )

    active = BooleanField(
        "Exibir na galeria",
        default=True,
    )

    submit = SubmitField("Adicionar foto")
