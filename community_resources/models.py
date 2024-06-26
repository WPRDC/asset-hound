from django.contrib.gis.db import models
from django.utils import timezone

from ckeditor.fields import RichTextField
from django.utils.text import slugify
from phonenumber_field.modelfields import PhoneNumberField
from recurrence.fields import RecurrenceField

from assets.models import Location


class Priority(models.IntegerChoices):
    TOP = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class WithNameSlug(object):
    name: models.CharField

    @property
    def slug(self):
        return slugify(self.name)


class ResourceCategory(models.Model, WithNameSlug):
    """ Resource Categories """
    name = models.CharField(max_length=100)
    description = models.TextField()
    image = models.ImageField(null=True, upload_to="icons")

    class Meta:
        verbose_name_plural = 'Resource Categories'

    def __str__(self):
        return self.name


class Population(models.Model, WithNameSlug):
    """ Groupings of folks based on commonalities """
    name = models.CharField(max_length=100)
    description = models.TextField()

    def __str__(self):
        return self.name


class Resource(models.Model, WithNameSlug):
    """ Individual services rendered, supplies distributed or other resources """
    name = models.CharField(max_length=500)
    description = RichTextField()

    # Contact Info
    phone_number = PhoneNumberField(null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    website = models.URLField(null=True, blank=True)

    # Categorization
    categories = models.ManyToManyField('ResourceCategory', related_name='resources')
    populations_served = models.ManyToManyField('Population', related_name='resources')

    # Locations
    assets = models.ManyToManyField("assets.Asset", related_name='resources', blank=True)
    other_locations = models.ManyToManyField("assets.Location", related_name='resources', blank=True)
    virtual_only = models.BooleanField()

    # Timing
    recurrence = RecurrenceField(null=True, blank=True)
    all_day = models.BooleanField(default=False)
    start_time = models.TimeField(
        help_text='If you selected "all day,"  you can leave this blank.',
        null=True,
        blank=True
    )
    end_time = models.TimeField(
        help_text='If you selected "all day,"  you can leave this blank.',
        null=True,
        blank=True
    )

    # Publishing info
    priority = models.IntegerField(
        help_text="This helps determine the order in which resources are listed.",
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    published = models.BooleanField(help_text="When checked, activity will show up on the site.", default=False)
    start_publish_date = models.DateField(
        "Start displaying on",
        help_text="After this date, the resource will show up on the site (default is today)",
        default=timezone.now
    )
    stop_publish_date = models.DateField(
        "Stop displaying after",
        help_text="After this date, the resource will stop showing up on the site (leave blank to keep up indefinitely)",
        null=True,
        blank=True
    )

    @property
    def virtual_only(self):
        return not len(self.assets.all()) and not len(self.other_locations.all())

    @property
    def publishable(self):
        return self.published and (self.start_date <= timezone.now() < self.stop_date)

    @property
    def locations(self):
        return Location.objects.filter(asset__in=self.assets.all()) | self.other_locations.all()

    class Meta:
        ordering = ('priority',)

    def __str__(self):
        return self.name


class CategorySection(models.Model, WithNameSlug):
    """  Stores rich content displayed in category sections of community pages. """
    community = models.ForeignKey('Community', related_name='category_sections', on_delete=models.CASCADE)
    category = models.ForeignKey('ResourceCategory', related_name='sections_by_community', on_delete=models.CASCADE)
    content = RichTextField()

    class Meta:
        unique_together = ['community', 'category']

    def __str__(self):
        return f'{self.community}/{self.category}'


class Community(models.Model, WithNameSlug):
    """ Primary unit of organization.

    Communities will each have their own pages and assigned users.
    Voltron (i.e. composite) neighborhoods. e.g. Hill District, North Side
    """
    name = models.CharField(max_length=500)

    neighborhoods = models.ManyToManyField('geo.Neighborhood')

    # Landing Page Content
    top_section_content = RichTextField(blank=True, default='')
    alert_content = RichTextField(blank=True, default='')

    resources = models.ManyToManyField('Resource', related_name='communities')

    @property
    def resource_categories(self):
        return ResourceCategory.objects.all()

    class Meta:
        verbose_name_plural = 'Communities'

    def __str__(self):
        return f'{self.name}'
