from rest_framework import viewsets, filters
from rest_framework.renderers import JSONRenderer
from rest_framework.pagination import LimitOffsetPagination

from rest_framework.settings import api_settings
from rest_framework_csv.renderers import CSVRenderer

from assets.models import RawAsset, Asset, AssetType, Category, Tag, TargetPopulation, ProvidedService, Location, Organization
from assets.serializers import AssetSerializer, AssetGeoJsonSerializer, AssetListSerializer, AssetTypeSerializer, \
    CategorySerializer, FullLocationSerializer

from assets.management.commands.util import parse_cell, standardize_phone

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from assets.forms import UploadFileForm
from assets.utils import distance

import os, pytz
from datetime import datetime, timedelta
from assets.tasks import sync_assets_to_carto_eventually

def there_is_a_field_to_update(row, fields_to_check):
    """Scan record for certain fields and see if any exist
    and are non-null (meaning that a Location could be
    created."""
    update_is_needed = False
    for field in fields_to_check:
        if field in row and row[field] not in ['', None]:
            return True
    return update_is_needed

def boolify(x): # This differs from the assets.management.commands.util versiion of boolify.
    if x.lower() in ['true', 't']:
        return True
    if x.lower() in ['false', 'f']:
        return False
    return None

def eliminate_empty_strings(xs):
    return [x for x in xs if x != '']

def non_blank_type_or_none(row, field, desired_type): # This could be imported from elsewhere.
    """This function tries to cast the value of row[field] to
    the passed desired type (e.g, float or int). If it fails,
    or if the passed value is an empty string (which is how
    None values are passed by CSVs), it returns None.

    Note that this does not yet support fields like
    PhoneNumberField, URLField, and EmailField."""
    if field in row:
        if row[field] == '':
            return None
        if desired_type == bool:
            return boolify(row[field])
        try:
            return desired_type(row[field])
        except ValueError:
            if desired_type == int:
                try:
                    return int(float(row[field])) # This is necessary to handle
                    # cases where Excel obliviously appends ".0" to integers.
                except ValueError:
                    return None
            return None
    return None

def pipe_delimit(xs):
    return '|'.join([str(x) for x in xs])

def list_of(named_things):
    # This converts ManyToManyField values back to a list.
    return [t.name for t in named_things.all()]

def check_or_update_value(instance, row, mode, more_results, source_field_name, field_type=str):
    if source_field_name not in row:
        return instance, more_results
    new_value = non_blank_type_or_none(row, source_field_name, field_type)

    old_value = getattr(instance, source_field_name)
    if new_value != old_value:
        more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
        setattr(instance, source_field_name, new_value)
    return instance, more_results


def modify_destination_asset(mode, row, destination_asset, created_new_asset, more_results):
    error = False
    if 'location_id' in row:
        location_id = row['location_id']
        if location_id in ['', None, 'new']:
            # Create a new Location instance to be populated.
            location = None # Location creation happens below.
        else:
            location = Location.objects.get(pk=location_id)
    else: # If the location_id field is omitted from the merge instructions,
        # fall back to the destination asset's location (which may be None).
        location = destination_asset.location

    # I'm choosing to not update the Location.name field here since we may want to manually name Location instances,
    # particularly to deal with cases like the two restaurant locations in Schenley Plaza that have the same
    # street address and parcel ID but slightly different geocoordinates.
    if location is None:
        if there_is_a_field_to_update(row, ['street_address', 'municipality', 'city', 'state', 'zip_code', 'parcel_id', 'latitude', 'longitude']):
            if mode == 'update':
                more_results.append(f"Creating a new Location for this Asset.")
            else:
                more_results.append(f"A new Location would be created for this Asset.")
            location = Location()
        elif there_is_a_field_to_update(row, ['residence', 'iffy_geocoding', 'unit', 'unit_type', 'available_transportation', 'geocoding_properties']):
            more_results.append("There is not enough information to create a new location for this Asset, but there are fields in the merge-instructions file which need to be assigned to a Location. Does not compute! ABORTING!!!<hr>")
            return None, more_results, True

    if 'organization_id' in row:
        organization_id = row['organization_id']
        if organization_id in ['', None, 'new']:
            # Create a new Organization instance to be populated.
            organization = None # Organization creation happens below.
        else:
            organization = Organization.objects.get(pk=organization_id)
    else: # If the organization_id field is omitted from the merge instructions,
        # fall back to the destination asset's organization (which may be None).
        organization = destination_asset.organization


    asset_name = row['name']
    if asset_name != destination_asset.name:
        more_results.append(f"asset_name {'will be ' if mode == 'validate' else ''}changed from {destination_asset.name} to {asset_name}.")
        destination_asset.name = asset_name

    # [ ] Oddball legacy conversion to be deleted:
    source_field_name = 'accessibility_features'
    if source_field_name in row:
        new_value = boolify(row[source_field_name])
        old_value = destination_asset.accessibility
        if new_value != old_value:
            more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
            destination_asset.accessibility = new_value


    missing_organization_identifier = True
    if 'organization_name' in row and row['organization_name'] not in ['', None]:
        missing_organization_identifier = False
    elif 'organization_id' in row and row['organization_id'] not in ['', None]:
        missing_organization_identifier = False
    # Which is about the same as what I originally wrote:
    #   missing_organization_identifier = (('organization_name' not in row) or (row['organization_name'] == '')) and (('organization_id' not in row) or (row['organization_id'] == ''))
    # but whatever.

    if missing_organization_identifier:
        # The organization can be identified EITHER by the organization_id value or by the organization_name value.
        if ('organization_phone' in row and row['organization_phone'] != '') or ('organization_email' in row and row['organization_email'] != ''):
            more_results.append(f"The organization's name or ID value is required if you want to change either the phone or e-mail address (as a check that the correct Organization instance is being updated. ABORTING!!!!\n<hr>.")
            return None, more_results, True
        #else: This is being removed for now since it seems like it could accidentally delete extant organizations.
        #    destination_asset.organization = None # Set ForiegnKey to None.
        #    more_results.append(f"&nbsp;&nbsp;&nbsp;&nbsp;Since the organization has not been clearly identified by name or ID, the Asset's organization is being set to None and other fields (organization_phone and organization email) are being ignored.")
    else:
        if organization is None:
            if mode == 'update':
                more_results.append(f"Creating a new Organization for this Asset.")
            else:
                more_results.append(f"A new Organization would be created for this Asset.")
            organization = Organization() # Create new organization instance.

        source_field_name = 'organization_name'
        destination_field_name = 'name'
        new_value = non_blank_type_or_none(row, source_field_name, str)
        old_value = organization.name
        if new_value != old_value:
            more_results.append(f"organization.{destination_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
            organization.name = new_value

        # check_or_update_value() can not be used without adding separate handling of source_field_name and destination_field_name.
        source_field_name = 'organization_email'
        if source_field_name in row:
            destination_field_name = 'email'
            new_value = non_blank_type_or_none(row, source_field_name, str)
            old_value = organization.email
            if new_value != old_value:
                more_results.append(f"organization.{destination_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
                organization.email = new_value

        source_field_name = 'organization_phone'
        if source_field_name in row:
            new_value = standardize_phone(non_blank_type_or_none(row, source_field_name, str))
            old_value = organization.phone
            if new_value != old_value:
                more_results.append(f"organization.{destination_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
                organization.phone = new_value

    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'street_address', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'unit', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'unit_type', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'municipality', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'city', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'state', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'zip_code', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'parcel_id', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'residence', field_type=bool)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'iffy_geocoding', field_type=bool)

    if 'latitude' in row or 'longitude' in row:
        old_latitude, old_longitude = location.latitude, location.longitude
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'latitude', field_type=float)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'longitude', field_type=float)
    if 'latitude' in row or 'longitude' in row:
        dist = distance(old_latitude, old_longitude, location.latitude, location.longitude)
        if dist is not None:
            more_results.append(f"&nbsp;&nbsp;&nbsp;&nbsp;The distance between the old and new coordinates is {dist:.2f} feet.")

    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'available_transportation', field_type=str)
    location, more_results = check_or_update_value(location, row, mode, more_results, source_field_name = 'geocoding_properties', field_type=str)

    # BEGIN Handle parent_location and parent_location_id
    source_field_name = 'parent_location_id'
    new_value = non_blank_type_or_none(row, source_field_name, str)
    old_value = getattr(getattr(location, 'parent_location', None), 'id', None)

    if new_value != old_value:
        more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
        new_parent_location = Location.objects.get(pk = new_value)
        setattr(location, 'parent_location', new_parent_location)

    if 'parent_location' in row:
        parent_location_name = getattr(getattr(location, 'parent_location', None), 'name', None)
        more_results.append(f"The parent_location name (after any parent_location_id updates) {'would be' if mode == 'validate' else 'is'} {parent_location_name}. [The 'parent_location' value in the merge-instructions file is not used to make updates.]")
    # END Handle parent_location and parent_location_id

    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'url', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'email', field_type=str)
    source_field_name = 'phone'
    if source_field_name in row:
        new_value = standardize_phone(non_blank_type_or_none(row, source_field_name, str))
        old_value = destination_asset.phone
        if new_value != old_value:
            more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {old_value} to {new_value}.")
            destination_asset.phone = new_value
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'hours_of_operation', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'holiday_hours_of_operation', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'periodicity', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'capacity', field_type=int)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'periodicity', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'wifi_network', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'wifi_notes', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'internet_access', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'computers_available', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'accessibility', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'open_to_public', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'child_friendly', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'sensitive', field_type=bool)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'localizability', field_type=str)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'etl_notes', field_type=str)

    # Unfortunately the many-to-many relations that follow can not be set on an Asset until it has been saved,
    # so for cases where created_new_asset == True, we have to save the Asset once at this point so it has an
    # id value.
    if created_new_asset and mode == 'update':
        destination_asset._change_reason = "Asset Updater: Initial save of Asset to allow many-to-many relationships"
        destination_asset.save(override_carto_sync = created_new_asset)
    destination_asset, more_results = check_or_update_value(destination_asset, row, mode, more_results, source_field_name = 'do_not_display', field_type=bool)
    # do_not_display must be set after the destination asset is initially saved since if
    # a new asset is created, it could be initially locationless and therefore have
    # do_not_display auto-set to True.

    source_field_name = 'asset_type'
    new_values = eliminate_empty_strings(row[source_field_name].split('|'))
    list_of_old_values = list_of(destination_asset.asset_types) if not created_new_asset else []
    if set(new_values) != set(list_of_old_values):
        more_results.append(f"asset_type {'will be ' if mode == 'validate' else ''}changed from {pipe_delimit(list_of_old_values)} to {pipe_delimit(new_values)}.")
        if new_values == []:
            more_results.append(f"asset_type can not be empty\n ABORTING!!!\n<hr>")
            return None, more_results, True
        try:
            validated_asset_types = [AssetType.objects.get(name=asset_type) for asset_type in new_values] # Change get to get_or_create to allow creation of new asset types.
            # It's better to require manual creation of new asset types for now since that encourages us to specify a Category (necessary for mapping).
            if mode == 'update':
                destination_asset.asset_types.set(validated_asset_types)
        except AssetType.DoesNotExist:
            more_results.append(f"Unable to find one of these asset types: {new_values}.\n ABORTING!!!\n<hr>")
            return None, more_results, True

    source_field_name = 'tags'
    if source_field_name in row:
        new_values = eliminate_empty_strings(row[source_field_name].split('|'))
        list_of_old_values = list_of(destination_asset.tags) if not created_new_asset else []
        if set(new_values) != set(list_of_old_values):
            more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {pipe_delimit(list_of_old_values)} to {pipe_delimit(new_values)}.")
            if mode == 'update':
                if new_values == []:
                    destination_asset.tags.clear()
                else:
                    validated_values = [Tag.objects.get_or_create(name=value)[0] for value in new_values]
                    destination_asset.tags.set(validated_values)

    source_field_name = 'services'
    if source_field_name in row:
        new_values = eliminate_empty_strings(row[source_field_name].split('|'))
        list_of_old_values = list_of(destination_asset.services) if not created_new_asset else []
        if set(new_values) != set(list_of_old_values):
            more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {pipe_delimit(list_of_old_values)} to {pipe_delimit(new_values)}.")
            if mode == 'update':
                if new_values == []:
                    destination_asset.services.clear()
                else:
                    validated_values = [ProvidedService.objects.get_or_create(name=value)[0] for value in new_values]
                    destination_asset.services.set(validated_values)

    source_field_name = 'hard_to_count_population'
    if source_field_name in row:
        new_values = eliminate_empty_strings(row[source_field_name].split('|'))
        list_of_old_values = list_of(destination_asset.hard_to_count_population) if not created_new_asset else []
        if set(new_values) != set(list_of_old_values):
            more_results.append(f"{source_field_name} {'will be ' if mode == 'validate' else ''}changed from {pipe_delimit(list_of_old_values)} to {pipe_delimit(new_values)}.")
            if mode == 'update':
                if new_values == []:
                    destination_asset.hard_to_count_population.clear()
                else:
                    validated_values = [TargetPopulation.objects.get_or_create(name=value)[0] for value in new_values]
                    destination_asset.hard_to_count_population.set(validated_values)

    # Fields that don't need to be updated: primary_key_from_rocket, synthesized_key, data_source_name, data_source_url
    return destination_asset, location, organization, more_results, False


def handle_uploaded_file(f, mode, using):
    import csv
    more_results = []

    assert using in ['using-raw-assets', 'using-assets']

    if f.size > 25000000:
        raise ValueError("handle_uploaded_file hasn't implemented saving the file for reading/parsing yet.")
        #for chunk in f.chunks(): # "Looping over chunks() instead of using read()
        #    # ensures that large files don't overwhelm your system's memory.
        #    destination.write(chunk)
    else:
        decoded_file = f.read().decode('utf-8').splitlines()

        # Validate the file
        if using == 'using-assets':
            reader = csv.DictReader(decoded_file)
            for row in reader:
                if 'asset_id' in row and row['asset_id'] not in ['']:
                    try:
                        assert row['asset_id'] == ''
                    except AssertionError:
                        more_results.append(f"id should be blank but is actually {row['asset_id']}. ASSET UPDATER FAILURE.")
                        return more_results

                if 'id' in row:
                    # Verify that this matches an Asset in the database.
                    raw_id = row['id']
                    if raw_id not in ['']:
                        try:
                            primary_asset_iterator = Asset.objects.filter(id = raw_id)
                            assert len(primary_asset_iterator) == 1 # To ensure it exists in the database.
                        except AssertionError:
                            more_results.append(f"Failed to find Asset with id == {raw_id}. ASSET UPDATER FAILURE.")
                            return more_results

                if 'ids_to_merge' in row:
                    # Verify that these match Assets in the database.
                    ids_to_merge = row['ids_to_merge']
                    if ids_to_merge not in ['']:
                        try:
                            asset_ids = [int(i) for i in ids_to_merge.split('+')]
                            assets_iterator = Asset.objects.filter(id__in = asset_ids)
                            assert len(assets_iterator) == len(asset_ids) # To ensure they all exist in the database.
                        except AssertionError:
                            more_results.append(f"Failed to find Assets with ids == {asset_ids}. ASSET UPDATER FAILURE.")
                            return more_results

                if 'location_id' in row and row['location_id'] not in ['', None]:
                    try:
                        location = Location.objects.get(pk = row['location_id'])
                    except Location.DoesNotExist:
                        more_results.append(f"Failed to find Location with id == {row['location_id']}. ASSET UPDATER FAILURE.")
                        return more_results

                if 'organization_id' in row and row['organization_id'] not in ['', None]:
                    try:
                        organization = Organization.objects.get(pk = row['organization_id'])
                    except Location.DoesNotExist:
                        more_results.append(f"Failed to find Organization with id == {row['location_id']}. ASSET UPDATER FAILURE.")
                        return more_results

        asset_ids_to_sync_to_carto = []
        reader = csv.DictReader(decoded_file)
        for row in reader:

            created_new_asset = False
            # Process the 'id' field
            raw_id = row['id']
            if using == 'using-raw-assets':
                primary_raw_asset_iterator = RawAsset.objects.filter(id = raw_id)
                assert len(primary_raw_asset_iterator) == 1 # To ensure it exists in the database.
                primary_raw_asset = primary_raw_asset_iterator[0]
            elif using == 'using-assets':
                primary_asset_iterator = Asset.objects.filter(id = raw_id)
                assert len(primary_asset_iterator) == 1 # To ensure it exists in the database.
                destination_asset = primary_asset_iterator[0] # Note that here
                # the primary asset is also the destination asset.

            # Process the 'asset_id' field
            if using == 'using-raw-assets':
                asset_id = row['asset_id']
                if asset_id in ['', None]:
                    created_new_asset = True
                    destination_asset = Asset()
                    more_results.append(f"A new Asset {'would' if mode == 'validate' else 'will'} be created.")
                else:
                    destination_asset_iterator = Asset.objects.filter(id = asset_id)
                    assert len(destination_asset_iterator) == 1 # To ensure there is exactly one in the database.
                    destination_asset = destination_asset_iterator[0]

            # Process the 'ids_to_merge' field
            ids_to_merge = row['ids_to_merge']
            if using == 'using-raw-assets':
                if ids_to_merge == '':
                    continue # Skip rows with no ids to merge.
                raw_ids = [int(i) for i in ids_to_merge.split('+')]
                raw_assets_iterator = RawAsset.objects.filter(id__in = raw_ids)
                assert len(raw_assets_iterator) == len(raw_ids) # To ensure they all exist in the database.
                raw_assets = list(raw_assets_iterator)
                for raw_asset in raw_assets:
                    raw_asset.asset = destination_asset

                if len(raw_assets) == 1:
                    if created_new_asset:
                        summary = f"{'Validating this process: ' if mode == 'validate' else ''}Creating a new Asset, "
                    else:
                        summary = f"{'Validating this process: ' if mode == 'validate' else ''}Editing the Asset with id = {asset_id}, previously named {destination_asset.name}, "
                    summary += f"and linking it to RawAsset with id = {raw_assets[0].id} and name = {raw_assets[0].name}."
                else:
                    summary = f"{'Validating this process: ' if mode == 'validate' else ''}Merging RawAssets with ids = {', '.join([str(r.id) for r in raw_assets])} and names = {', '.join([r.name for r in raw_assets])} "
                    if created_new_asset:
                        summary += f" to a new Asset with name {row.get('name', '(No name given)')}."
                    else:
                        summary += f" to Asset with id = {asset_id}, previously named {destination_asset.name}."
                more_results.append(summary)

            elif using == 'using-assets':
                # When merging Assets, the Asset that is not the destination
                # asset should be delisted.
                if mode == 'update':
                    if ids_to_merge == '':
                        destination_asset.do_not_display = True
                        destination_asset._change_reason = f'Asset Updater: Delisting Asset'
                        destination_asset.save(override_carto_sync = True)
                        asset_ids_to_sync_to_carto.append(destination_asset.id)
                        s = f"Delisting {destination_asset.name}."
                        more_results.append(s)
                        continue # Skip rows with no ids to merge.
                    asset_ids = [int(i) for i in ids_to_merge.split('+')]
                    assert destination_asset.id in asset_ids

                    assets_iterator = Asset.objects.filter(id__in = asset_ids)
                    assert len(assets_iterator) == len(asset_ids) # To ensure they all exist in the database.
                    s = f"{'Validating this process: ' if mode == 'validate' else ''}Editing the Asset with id = {destination_asset.id}, previously named {destination_asset.name}."
                    more_results.append(s)
                    if len(assets_iterator) > 1:
                        s = f"Delisting extra Assets (from the list {ids_to_merge}) and assigning corresponding RawAssets to the destination Asset."
                        more_results.append(s)

                    for asset in assets_iterator:
                        if destination_asset.id is not None and asset.id != destination_asset.id:
                            asset.do_not_display = True # These Assets could be deleted (rather than delisted)
                            # AFTER reassinging their RawAssets.
                            asset._change_reason = f'Asset Updater: Delisting Asset'
                            asset.save()
                            asset_ids_to_sync_to_carto.append(asset.id)

                            # Iterate over raw assets of this asset and point them to destination_asset.
                            for raw_asset in asset.rawasset_set.all():
                                raw_asset.asset = destination_asset
                                raw_asset._change_reason = f'Asset Updater: Linking RawAsset to different Asset because of Asset merge'
                                raw_asset.save() # This saving couldn't be done below
                                # because there can be multiple sets of RawAssets. They'd
                                # all have to be collected into raw_assets to do it below.
                else:
                    if '+' in ids_to_merge:
                        s = f"Extra Assets (from the list {ids_to_merge}) would be delisted and corresponding RawAssets would be assigned to the destination Asset."
                        more_results.append(s)
                    elif ids_to_merge == '':
                        s = f"{destination_asset.name} would be delisted."
                        more_results.append(s)

            ### At this point the fields that differentiate Asset-based Asset updates from
            ### RawAsset-based Asset updates have been processed.
            ### What comes out of this stage is destination_asset and raw_assets.
            destination_asset, location, organization, more_results, error = modify_destination_asset(mode, row, destination_asset, created_new_asset, more_results)
            if error:
                return more_results

            if mode == 'update':
                more_results.append(f"Updating associated Asset, RawAsset, Location, and Organization instances. (This may leave some orphaned.)\n")
                more_results.append(f'&nbsp;&nbsp;&nbsp;&nbsp;<a href="https://assets.wprdc.org/api/dev/assets/assets/{destination_asset.id}/" target="_blank">Updated Asset</a>\n')
                change_reason = f'Asset Updater: {"Creating new " if created_new_asset else "Updating "}Asset'
                destination_asset._change_reason = change_reason
                destination_asset.save(override_carto_sync = True) # Is this save actually necessary, given that there's another below?

                if using == 'using-raw-assets':
                    for raw_asset in raw_assets: # RawAssets must be saved first because an Asset needs at least one
                        # linked RawAsset or else it will automatically have do_not_display set to True.
                        raw_asset._change_reason = f'Asset Updater: Linking to {"new " if created_new_asset else ""}Asset'
                        raw_asset.save()

                if organization is not None:
                    organization._change_reason = change_reason
                    organization.save()
                if location is not None:
                    location._change_reason = change_reason
                    location.save()
                    more_results.append(f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<a href="https://assets.wprdc.org/api/dev/assets/locations/{location.id}/" target="_blank">Linked Location</a>\n<hr>')
                destination_asset.location = location
                destination_asset.organization = organization
                destination_asset._change_reason = change_reason
                destination_asset.save(override_carto_sync = True)
                asset_ids_to_sync_to_carto.append(destination_asset.id)
            else:
                more_results.append(f"\n<hr>")

    if mode == 'update' and len(asset_ids_to_sync_to_carto) > 0:
        sync_assets_to_carto_eventually(asset_ids_to_sync_to_carto)
    more_results.append(f"\nasset_ids_to_sync_to_carto = {asset_ids_to_sync_to_carto}")
    return more_results

@staff_member_required
def upload_file(request, using):
    # The "using" parameter should have either the value "using-raw-assets" or
    # the value "using-assets".
    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            if 'validate' in request.POST: # The user hit the "Validate" button:
                mode = "validate"
            else:
                mode = "update"
            results = handle_uploaded_file(request.FILES['file'], mode, using)
            return render(request, 'update.html', {'form': form, 'results': results, 'asset_based': using == 'using-assets'})
    else:
        form = UploadFileForm()
    return render(request, 'update.html', {'form': form, 'results': [], 'asset_based': using == 'using-assets'})

def dump_assets(filepath):
    from django.core.management import call_command
    call_command('dump_assets_all_fields', filepath)

@staff_member_required
def request_asset_dump(request):
    filepath = '/home/david/downloads/asset_dump.csv'
    if os.path.exists(filepath): # Clear the file if it exists.
        os.remove(filepath)

    # This SHOULD run the process as a separate thread, allowing it to
    # complete after the page is rendered.
    #   t = threading.Thread(target=dump_assets, args=[filepath], daemon=True)
    #   t.start()
    # but it doesn't. Only 30 lines are written (though the web page does render).
    dump_assets(filepath) # This works but results in a broken web page.
    record_count = len(Asset.objects.all())
    minutes = record_count/32731*7 + 1
    estimated_completion_time_utc = (datetime.utcnow() + timedelta(minutes=minutes))
    eta_local = estimated_completion_time_utc.astimezone(pytz.timezone('America/New_York')).time().strftime("%H:%M")
    return render(request, 'dump.html', {'url': 'https://assets.wprdc.org/asset_dump.csv', 'eta': eta_local})

class AssetViewSet(viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (CSVRenderer, )
    queryset = Asset.objects.all()
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['name',]

    def get_serializer_class(self, *args, **kwargs):
        fmt = self.request.GET.get('fmt', None)
        if fmt in ('geojson', 'geo'):
            return AssetGeoJsonSerializer
        if self.action == 'list':
            return AssetListSerializer
        return AssetSerializer


class AssetTypeViewSet(viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (CSVRenderer, )
    queryset = AssetType.objects.all()
    serializer_class = AssetTypeSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (CSVRenderer, )
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class LocationViewSet(viewsets.ModelViewSet):
    # Note that this view is designed for easy access to the full model from a Python
    # script, so it uses a full-model serializer and the Django REST Framework's
    # default snake-case JSON renderer.
    renderer_classes = (JSONRenderer, CSVRenderer)
    queryset = Location.objects.all()
    serializer_class = FullLocationSerializer
