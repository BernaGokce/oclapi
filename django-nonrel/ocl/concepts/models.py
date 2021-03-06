from urlparse import urljoin
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from djangotoolbox.fields import ListField, EmbeddedModelField
from uuidfield import UUIDField
from concepts.mixins import DictionaryItemMixin
from oclapi.models import (SubResourceBaseModel, ResourceVersionModel,
                           VERSION_TYPE, ACCESS_TYPE_EDIT, ACCESS_TYPE_VIEW)
from sources.models import SourceVersion, Source
from django.db.models import get_model


class LocalizedText(models.Model):
    uuid = UUIDField(auto=True)
    external_id = models.TextField(null=True, blank=True)
    name = models.TextField()
    type = models.TextField(null=True, blank=True)
    locale = models.TextField()
    locale_preferred = models.BooleanField(default=False)

    def clone(self):
        return LocalizedText(
            uuid=self.uuid,
            external_id=self.external_id,
            name=self.name,
            type=self.type,
            locale=self.locale,
            locale_preferred=self.locale_preferred
        )


CONCEPT_TYPE = 'Concept'


class Concept(SubResourceBaseModel, DictionaryItemMixin):
    external_id = models.TextField(null=True, blank=True)
    concept_class = models.TextField()
    datatype = models.TextField(null=True, blank=True)
    names = ListField(EmbeddedModelField(LocalizedText))
    descriptions = ListField(EmbeddedModelField(LocalizedText))
    retired = models.BooleanField(default=False)

    @property
    def display_name(self):
        return self.get_display_name_for(self)

    @property
    def display_locale(self):
        return self.get_display_locale_for(self)

    @property
    def owner(self):
        return self.parent.owner

    @property
    def owner_name(self):
        return self.parent.owner_name

    @property
    def owner_type(self):
        return self.parent.owner_type

    @property
    def owner_url(self):
        return self.parent.owner_url

    @property
    def num_versions(self):
        return ConceptVersion.objects.filter(versioned_object_id=self.id).count()

    @property
    def names_for_default_locale(self):
        names = []
        for name in self.names:
            if settings.DEFAULT_LOCALE == name.locale:
                names.append(name.name)
        return names

    @property
    def descriptions_for_default_locale(self):
        descriptions = []
        for desc in self.descriptions:
            if settings.DEFAULT_LOCALE == desc.locale:
                descriptions.append(desc.name)
        return descriptions

    @property
    def num_stars(self):
        return 0

    def get_bidirectional_mappings(self):
        module = __import__('mappings.models', fromlist=['models'])
        class_ = getattr(module, 'Mapping')
        queryset = class_.objects.filter(parent=self.parent)
        return queryset.filter(Q(from_concept=self) | Q(to_concept=self))

    def get_unidirectional_mappings(self):
        module = __import__('mappings.models', fromlist=['models'])
        class_ = getattr(module, 'Mapping')
        return class_.objects.filter(parent=self.parent, from_concept=self)

    def get_empty_mappings(self):
        return []

    @classmethod
    def resource_type(cls):
        return CONCEPT_TYPE

    @classmethod
    def create_initial_version(cls, obj, **kwargs):
        initial_version = ConceptVersion.for_concept(obj, '--TEMP--')
        initial_version.save()
        initial_version.mnemonic = initial_version.id
        initial_version.root_version = initial_version
        initial_version.released = True
        initial_version.save()
        return initial_version

    @classmethod
    def retire(cls, concept, user):
        if concept.retired:
            return {'__all__': 'Concept is already retired'}
        latest_version = ConceptVersion.get_latest_version_of(concept)
        retired_version = latest_version.clone()
        retired_version.retired = True
        retired_version.update_comment = 'Concept was retired'
        errors = ConceptVersion.persist_clone(retired_version, user)
        if not errors:
            concept.retired = True
            concept.save()
        return errors

    @classmethod
    def unretire(cls, concept, user):
        if not concept.retired:
            return {'__all__': 'Concept is already not retired'}
        latest_version = ConceptVersion.get_latest_version_of(concept)
        unretired_version = latest_version.clone()
        unretired_version.retired = False
        unretired_version.update_comment = 'Concept was un-retired'
        errors = ConceptVersion.persist_clone(unretired_version, user)
        if not errors:
            concept.retired = False
            concept.save()
        return errors

    @classmethod
    def count_for_source(cls, src, is_active=True, retired=False):
        return cls.objects.filter(parent_id=src.id, is_active=is_active, retired=retired)

    @staticmethod
    def get_url_kwarg():
        return 'concept'

    @staticmethod
    def get_display_name_for(obj):
        if not obj.names:
            return None
        for name in obj.names:
            if name.locale_preferred:
                return name.name
        return obj.names[0].name

    @staticmethod
    def get_display_locale_for(obj):
        if not obj.names:
            return None
        for name in obj.names:
            if name.locale_preferred:
                return name.locale
        return obj.names[0].locale

    @staticmethod
    def get_version_model():
        return ConceptVersion

    @property
    def get_latest_version(self):
        return ConceptVersion.objects.filter(versioned_object_id=self.id).order_by('-created_at')[:1][0]


class ConceptVersion(ResourceVersionModel):
    external_id = models.TextField(null=True, blank=True)
    concept_class = models.TextField()
    datatype = models.TextField(null=True, blank=True)
    names = ListField(EmbeddedModelField('LocalizedText'))
    descriptions = ListField(EmbeddedModelField('LocalizedText'))
    retired = models.BooleanField(default=False)
    root_version = models.ForeignKey('self', null=True, blank=True)
    is_latest_version = models.BooleanField(default=True)
    version_created_by = models.TextField()
    update_comment = models.TextField(null=True, blank=True)

    def clone(self):
        return ConceptVersion(
            mnemonic='--TEMP--',
            public_access=self.public_access,
            external_id=self.external_id,
            concept_class=self.concept_class,
            datatype=self.datatype,
            names=map(lambda n: n.clone(), self.names),
            descriptions=map(lambda d: d.clone(), self.descriptions),
            retired=self.retired,
            versioned_object_id=self.versioned_object_id,
            versioned_object_type=self.versioned_object_type,
            released=self.released,
            previous_version=self,
            parent_version=self.parent_version,
            root_version=self.root_version,
            is_latest_version=self.is_latest_version,
            extras=self.extras
        )

    @property
    def name(self):
        return self.versioned_object.mnemonic

    @property
    def owner(self):
        return self.versioned_object.owner

    @property
    def owner_name(self):
        return self.versioned_object.owner_name

    @property
    def owner_type(self):
        return self.versioned_object.owner_type

    @property
    def owner_url(self):
        return self.versioned_object.owner_url

    @property
    def display_name(self):
        return Concept.get_display_name_for(self)

    @property
    def display_locale(self):
        return Concept.get_display_locale_for(self)

    @property
    def source(self):
        return self.versioned_object.parent

    @property
    def collections(self):
        versions = self.collection_versions
        return map(lambda v: v.versioned_object, versions)

    @property
    def collection_ids(self):
        return map(lambda c: c.id, get_model('collection', 'Collection').objects.filter(references={'expression': self.versioned_object.uri})) if self.is_latest_version else []

    @property
    def collection_versions(self):
        return get_model('collection', 'CollectionVersion').objects.filter(concepts=self.id)

    @property
    def collection_version_ids(self):
        return map(lambda v: v.id, self.collection_versions)

    @property
    def mappings_url(self):
        concept = self.versioned_object
        source = concept.parent
        owner = source.owner
        owner_kwarg = 'user' if isinstance(owner, User) else 'org'
        return reverse(
            'concept-mapping-list',
            kwargs={'concept': concept.mnemonic,
                    'source': source.mnemonic,
                    owner_kwarg: owner.mnemonic})

    @property
    def names_for_default_locale(self):
        names = []
        for name in self.names:
            if settings.DEFAULT_LOCALE == name.locale:
                names.append(name.name)
        return names

    @property
    def all_names(self):
        names = []
        for name in self.names:
            names.append(name.name)
        return names

    @property
    def descriptions_for_default_locale(self):
        descriptions = []
        for desc in self.descriptions:
            if settings.DEFAULT_LOCALE == desc.locale:
                descriptions.append(desc.name)
        return descriptions

    @property
    def is_root_version(self):
        return self == self.root_version

    @property
    def public_can_view(self):
        return self.source.public_access in [ACCESS_TYPE_EDIT, ACCESS_TYPE_VIEW]

    def get_empty_mappings(self):
        return self.versioned_object.get_empty_mappings()

    def get_unidirectional_mappings(self):
        return self.versioned_object.get_unidirectional_mappings()

    def get_bidirectional_mappings(self):
        return self.versioned_object.get_bidirectional_mappings()

    @classmethod
    def get_latest_version_of(cls, concept):
        versions = ConceptVersion.objects.filter(
            versioned_object_id=concept.id, is_latest_version=True).order_by('-created_at')
        return versions[0] if versions else None

    @classmethod
    def get_latest_version_by_id(cls, id):
        versions = ConceptVersion.objects.filter(
            versioned_object_id=id, is_latest_version=True).order_by('-created_at')
        return versions[0] if versions else None

    @classmethod
    def for_concept(cls, concept, label, previous_version=None, parent_version=None):
        return ConceptVersion(
            mnemonic=label,
            public_access=concept.public_access,
            external_id=concept.external_id,
            concept_class=concept.concept_class,
            datatype=concept.datatype,
            extras=concept.extras,
            names=concept.names,
            descriptions=concept.descriptions,
            retired=concept.retired,
            versioned_object_id=concept.id,
            versioned_object_type=ContentType.objects.get_for_model(Concept),
            released=False,
            previous_version=previous_version,
            parent_version=parent_version,
            version_created_by=concept.created_by,
            created_by=concept.created_by,
            updated_by=concept.updated_by,
        )

    @classmethod
    def diff(cls, v1, v2):
        diffs = {}
        if v1.public_access != v2.public_access:
            diffs['public_access'] = {'was': v1.public_access, 'is': v2.public_access}
        if v1.external_id != v2.external_id:
            diffs['external_id'] = {'was': v1.external_id, 'is': v2.external_id}
        if v1.concept_class != v2.concept_class:
            diffs['concept_class'] = {'was': v1.concept_class, 'is': v2.concept_class}
        if v1.datatype != v2.datatype:
            diffs['datatype'] = {'was': v1.datatype, 'is': v2.datatype}

        # Diff names
        names1 = v1.names
        names2 = v2.names
        diff = len(names1) != len(names2)
        if not diff:
            n1 = sorted(names1, key=lambda n: n.name)
            n2 = sorted(names2, key=lambda n: n.name)
            for i, n in enumerate(n1):
                if n.external_id != n2[i].external_id:
                    diff = True
                    break
                if n.name != n2[i].name:
                    diff = True
                    break
                if n.type != n2[i].type:
                    diff = True
                    break
                if n.locale != n2[i].locale:
                    diff = True
                    break
                if n.locale_preferred != n2[i].locale_preferred:
                    diff = True
                    break
        if diff:
            diffs['names'] = True

        # Diff descriptions
        names1 = v1.descriptions
        names2 = v2.descriptions
        diff = len(names1) != len(names2)
        if not diff:
            n1 = sorted(names1, key=lambda n: n.name)
            n2 = sorted(names2, key=lambda n: n.name)
            for i, n in enumerate(n1):
                if n.external_id != n2[i].external_id:
                    diff = True
                    break
                if n.name != n2[i].name:
                    diff = True
                    break
                if n.type != n2[i].type:
                    diff = True
                    break
                if n.locale != n2[i].locale:
                    diff = True
                    break
                if n.locale_preferred != n2[i].locale_preferred:
                    diff = True
                    break
        if diff:
            diffs['descriptions'] = True

        # Diff extras
        extras1 = v1.extras if v1.extras else {}
        extras2 = v2.extras if v2.extras else {}
        diff = len(extras1) != len(extras2)
        if not diff:
            for key in extras1:
                if key not in extras2:
                    diff = True
                    break
                if extras2[key] != extras1[key]:
                    diff = True
                    break
        if diff:
            diffs['extras'] = {'was': extras1, 'is': extras2}

        return diffs

    @classmethod
    def persist_clone(cls, obj, user=None, **kwargs):
        errors = dict()
        if not user:
            errors['version_created_by'] = 'Must specify which user is attempting to create a new concept version.'
            return errors
        obj.version_created_by = user.username
        previous_version = obj.previous_version
        previous_was_latest = previous_version.is_latest_version and obj.is_latest_version
        source_version = SourceVersion.get_head_of(obj.versioned_object.parent)
        persisted = False
        errored_action = 'saving new concept version'
        try:
            obj.save(**kwargs)
            obj.mnemonic = obj.id
            obj.save()

            errored_action = "updating 'is_latest_version' attribute on previous version"
            if previous_was_latest:
                previous_version.is_latest_version = False
                previous_version.save()

            errored_action = 'replacing previous version in latest version of source'
            source_version.update_concept_version(obj)

            # Mark versioned object as updated
            concept = obj.versioned_object
            concept.extras = obj.extras
            concept.save()

            persisted = True
        finally:
            if not persisted:
                source_version.update_concept_version(obj.previous_version)
                if previous_was_latest:
                    previous_version.is_latest_version = True
                    previous_version.save()
                if obj.id:
                    obj.delete()
                errors['non_field_errors'] = ['An error occurred while %s.' % errored_action]
        return errors

    @classmethod
    def resource_type(cls):
        return VERSION_TYPE

    @classmethod
    def versioned_resource_type(cls):
        return CONCEPT_TYPE

    @staticmethod
    def get_url_kwarg():
        return 'concept_version'


# class ConceptReference(SubResourceBaseModel, DictionaryItemMixin):
#     concept = models.ForeignKey(Concept)
#     concept_version = models.ForeignKey(ConceptVersion, null=True, blank=True)
#     source_version = models.ForeignKey(SourceVersion, null=True, blank=True)
#
#     def clean(self):
#         if self.concept_version and self.source_version:
#             raise ValidationError('Cannot specify both source_version and concept_version.')

    # @property
    # def concept_reference_url(self):
    #     if self.source_version:
    #         source_version_url = reverse_resource_version(self.source_version,
    #                                                       'sourceversion-detail')
    #         return urljoin(source_version_url, 'concepts/%s/' % self.concept.mnemonic)
    #     if self.concept_version:
    #         return reverse_resource_version(self.concept_version, 'conceptversion-detail')
    #     return reverse_resource(self.concept, 'concept-detail')

    # @property
    # def concept_class(self):
    #     return self.concept.concept_class if self.concept else None
    #
    # @property
    # def data_type(self):
    #     return self.concept.datatype if self.concept else None
    #
    # @property
    # def source(self):
    #     return self.concept.parent if self.concept else None
    #
    # @property
    # def collection(self):
    #     return self.parent.mnemonic if self.parent else None
    #
    # @property
    # def owner_name(self):
    #     return self.parent.owner_name if self.parent else None
    #
    # @property
    # def owner_type(self):
    #     return self.parent.owner_type if self.parent else None
    #
    # @property
    # def owner_url(self):
    #     return self.parent.owner_url if self.parent else None
    #
    # @property
    # def display_name(self):
    #     return self.concept.display_name if self.concept else None
    #
    # @property
    # def display_locale(self):
    #     return self.concept.display_locale if self.concept else None
    #
    # @property
    # def is_current_version(self):
    #     return not(self.concept_version or self.source_version)
    #
    # @staticmethod
    # def get_url_kwarg():
    #     return 'concept'


@receiver(post_save, sender=Source)
def propagate_parent_attributes(sender, instance=None, created=False, **kwargs):
    if created:
        return
    for concept in Concept.objects.filter(parent_id=instance.id):
        update_index = False
        if concept.is_active != instance.is_active:
            update_index = True
            concept.is_active = instance.is_active
        if concept.public_access != instance.public_access:
            update_index |= True
            concept.public_access = instance.public_access
        if update_index:
            for concept_version in ConceptVersion.objects.filter(versioned_object_id=concept.id):
                concept_version.is_active = instance.is_active
                concept_version.public_access = instance.public_access
                concept_version.save()
            concept.save()


# @receiver(post_save, sender=ConceptVersion)
# def update_references(sender, instance=None, created=False, **kwargs):
#     #Update all references...
#
#     # WHERE concept_version_id = this ConceptVersion ID
#     or_clauses = [Q(concept_version_id=instance.id)]
#
#     # OR concept_id = this ConceptVersion's Concept ID,
#     #    AND source_version_id refers to one of the source versions containing this ConceptVersion
#     concept = instance.versioned_object
#     source_versions = SourceVersion.objects.filter(versioned_object_id=concept.parent_id)
#     source_versions_with_concept = []
#     for source_version in source_versions:
#         if instance.id in source_version.concepts:
#             source_versions_with_concept.append(source_version.id)
#     or_clauses.append(
#         Q(concept_id=concept.id, source_version_id__in=source_versions_with_concept))
#
#     # Do the update
#     for ref in ConceptReference.objects.filter(reduce(lambda x, y: x | y, or_clauses[1:], or_clauses[0])):
#         ref.save()
#
#     # OR if ConceptVersion is the latest version
#     if instance.is_latest_version:
#         # Updated all references that don't specify a concept version
#         for ref in ConceptReference.objects.filter(concept_id=instance.versioned_object_id):
#             if ref.is_current_version:
#                 ref.save()
