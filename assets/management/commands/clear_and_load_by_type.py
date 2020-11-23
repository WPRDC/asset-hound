import csv
import os
import re
import sys  # This is a workaround for an error that
csv.field_size_limit(sys.maxsize)  # looks like this:
# _csv.Error: field larger than field limit (131072)

import phonenumbers
from django.conf import settings
from django.core.management.base import BaseCommand

from assets.models import (Asset,
                           Organization,
                           Location,
                           AssetType,
                           Tag,
                           ProvidedService,
                           TargetPopulation,
                           DataSource)

from assets.management.commands.util import parse_cell, get_localizability, boolify, standardize_phone

from pprint import pprint


def boolify(x): # This differs from the assets.management.commands.util version of boolify.
    if x.lower() in ['true', 't']:
        return True
    if x.lower() in ['false', 'f']:
        return False
    return None

def non_blank_value_or_none(row, field):
    """If the field is in the row dict, return the value (unless it's an empty
    string, which gets coerced to None).
    Otherwise return None."""
    return row[field] if (field in row and row[field] != '') else None

def non_blank_type_or_none(row, field, desired_type):
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
            return None
    return None

def get_location_by_keys(row, keys):
    # When you don't know the field names ahead of time, you can use kwargs to pass the key field names and values to the queryset.
    #Location.objects.filter(**{'string__contains': 'search_string'})
    kwargs = {}
    for key in keys:
        assert key not in ['residence']
        actual_key = key.split('__')[0]
        if key == 'zip_code__startswith':
            full_zip_code = non_blank_value_or_none(row, actual_key)
            if full_zip_code is not None:
                kwargs[key] = full_zip_code[:5]
        else:
            value = non_blank_value_or_none(row, actual_key)
            if value is not None:
                kwargs[key] = value

    #  [ ] Where is boolify used on residence?
    #  Do I need to do something like this?
    # (cast latitude and longitude to float)
    # in the query here? Will that lead to problems?


    # [ ] Think through this more carefully to see what to do in
    # cases where some values are None but others aren't.
    # Like city = 'Pittsburgh' and state = None and street_address = None.

    # If all values are None, return None, False
    if all([v is None for v in kwargs.values()]):
        return None, False
    if any([v is None for v in kwargs.values()]): # This should no longer trigger based on the above reworking (e.g., "if value is not None").
        print(f"There are some null values in this query: {kwargs}.")

    if 'latitude' not in keys and 'longitude' not in keys:
        locations = Location.objects.filter(**kwargs).order_by('-id')
    else: # Floating point values are not good ones to query on directly.
        # Options include using the DecimalField or (as chosen here)
        # filtering on ranges.
        if 'geocoding_properties' not in row or 'centroid' not in row['geocoding_properties']:
            assert set(keys) == set(['latitude', 'longitude'])
            latitude = non_blank_type_or_none(row, 'latitude', float)
            longitude = non_blank_type_or_none(row, 'longitude', float)
            if latitude is None or longitude is None:
                return None, False
            resolution = 10**-6 # This value should be thought through some more.
            locations = Location.objects.filter(latitude__gte = latitude - resolution,
                    latitude__lte = latitude + resolution,
                    longitude__gte = longitude - resolution,
                    longitude__lte = longitude + resolution).order_by('-id')

    if len(locations) == 0:
        return None, False
    if len(locations) == 1:
        return locations[0], True
    # Otherwise pick the one with the largest id value, which is the first
    # one because of the order_by('-id') part of the query.
    print(f"Found {len(locations)}. Returning the one with the highest ID.")
    return locations[0], True


def update_or_create_location(row):
    # Try to find a pre-existing record by keys. Otherwise create it.
    # Any other fields should be used to fill in gaps and (maybe someday used in clever updating).

    location_created = False
    keys = ['street_address__iexact', 'city__iexact', 'state__iexact', 'zip_code__startswith']
    # Sneak better querying in through the keys.
    location, location_obtained = get_location_by_keys(row, keys)

    if location_obtained:
        effective_keys = list(keys)
    else:
        keys = ['latitude', 'longitude']
        location, location_obtained = get_location_by_keys(row, keys)

        if location_obtained:
            effective_keys = list(keys)
        else: # Create a location instance.
            kwargs = {}
            kwargs['street_address'] = non_blank_value_or_none(row, 'street_address')
            kwargs['city'] = non_blank_value_or_none(row, 'city')
            kwargs['state'] = non_blank_value_or_none(row, 'state')
            kwargs['zip_code'] = non_blank_value_or_none(row, 'zip_code')
            kwargs['available_transportation'] = non_blank_value_or_none(row, 'location_transportation')
            kwargs['latitude'] = non_blank_type_or_none(row, 'latitude', float)
            kwargs['longitude'] = non_blank_type_or_none(row, 'longitude', float)
            kwargs['residence'] = boolify(non_blank_value_or_none(row, 'residence'))
            kwargs['geocoding_properties'] = non_blank_value_or_none(row, 'geocoding_properties')
            kwargs['parcel_id'] = non_blank_value_or_none(row, 'parcel_id')
            location = Location(**kwargs)
            location.save()
            location_obtained = True
            location_created = True

    assert location_obtained

    #location, location_created = Location.objects.get_or_create(
    #    street_address=non_blank_value_or_none(row, 'street_address'),
    #    city=non_blank_value_or_none(row, 'city'),
    #    state=non_blank_value_or_none(row, 'state'),
    #    zip_code=non_blank_value_or_none(row, 'zip_code'),
    #    defaults={
    #        'available_transportation': non_blank_value_or_none(row, 'location_transportation'),
    #        'latitude': non_blank_type_or_none(row, 'latitude', float),
    #        'longitude': non_blank_type_or_none(row, 'longitude', float),
    #        'geocoding_properties': non_blank_value_or_none(row, 'geocoding_properties'),
    #        'parcel_id': non_blank_value_or_none(row, 'parcel_id'),
    #        'residence': boolify(non_blank_value_or_none(row, 'residence')),
    #    }
    #)

    # How to get the value of an object based on the field name (when the field name is a variable).
    #obj = MyModel.objects.first()
    #field_value = getattr(obj, field_name)


    # [ ] Eventually a more sophisticated merging approach will be needed to combine
    # different bits of location data from different assets into one Location object.
    # At present, this is just filling in gaps but not handling conflicts.
    if not location_created:
        if 'street_address' not in effective_keys and 'city' not in effective_keys and 'state' not in effective_keys and 'zip_code' not in effective_keys:
            # Update these as a block so that these values are consistent.
            if location.street_address is None and location.city is None and location.state is None and location.zip_code is None:
                # We are only doing this update when ALL values are None to avoid an unstable situation
                # where every time this script is run, the location can toggle between location data for
                # two or more different records.
                location.street_address = non_blank_value_or_none(row, 'street_address')
                location.city = non_blank_value_or_none(row, 'city')
                location.state = non_blank_value_or_none(row, 'state')
                location.zip_code = non_blank_value_or_none(row, 'zip_code')


        if 'latitude' not in effective_keys and 'longitude' not in effective_keys and 'geocoordinates' not in effective_keys: # OR if the intersection of these lists is empty...
            if location.latitude is None and location.longitude is None:
            #if True or location.latitude is None or location.longitude is None: # Delete this after one iteration. This just sets the geocoordinates # of previously automatically and badly geocoded Locations.
            # Update these as a block so that these values are consistent.
                location.latitude = non_blank_type_or_none(row, 'latitude', float)
                location.longitude = non_blank_type_or_none(row, 'longitude', float)
                location.geocoding_properties = non_blank_value_or_none(row, 'geocoding_properties')
            #else:
            # There may be a geocoordinates conflict, but there may be so many of these
            # that handling these at this stage may not be feasible.

        if 'available_transportation' not in effective_keys:
            if location.available_transportation is None:
                location.available_transportation = non_blank_value_or_none(row, 'location_transportation')
            #else: # Append to existing list (if not already there).
            #    extant_options = location.available_transportation.split('|')
            #    new_available_transportation = non_blank_value_or_none(row, 'location_transportation')
            #    if new_available_transportation not in extant_options:
            #        location.available_transportation = f"{location.available_transportation}|{new_available_transportation}"
            # [ ] Don't do this yet (because the field might not be big enough).

        if 'parcel_id' not in effective_keys:
            if location.parcel_id is None:
               location.parcel_id = non_blank_value_or_none(row, 'parcel_id')
           # else: # Append to existing list (if not already there).
           #     extant_options = location.parcel_id.split('|')
           #     new_option = non_blank_value_or_none(row, 'parcel_id')
           #     if new_option not in extant_options:
           #         location.parcel_id = f"{location.parcel_id}|{new_option}"
           # [ ] Don't do this yet (because the field is definitely not big enough and might need to be huge).

        if 'residence' not in effective_keys:
            asset_is_residence = boolify(non_blank_value_or_none(row, 'residence'))
            if asset_is_residence is not None:
                if location.residence is None:
                    location.residence = asset_is_residence
                else: # What should we do if one data source says that the location is
                    # not a residence and the other says that it is?
                    # It could be that one is wrong about whether it is a residence
                    # or about the address, or it could be an apartment on top of
                    # a store. In any event, if there's a conflict, throw an exception.
                    if location.residence != asset_is_residence:
                        raise ValueError(f"The location {Location.name} has residence == {location.residence}, but this new asset ({non_blank_value_or_none(row, 'name')}) of type {row['asset_type']} has residence == {asset_is_residence}.")
                    # Otherwise the values agree, and no update is needed.

    location.save()
    return location, location_created

class Command(BaseCommand):
    help = 'Loads assets from a CSV file, which may be specified by a command-line argument.'

    def add_arguments(self, parser): # Necessary boilerplate for accessing args.
        parser.add_argument('args', nargs='*')

    def handle(self, *args, **options):

        override_clearing = True # Sometimes we may not want to clear assets when loading assets.
        # In fact, eventually loading based on primary_key_from_rocket/synthesized_key will be the default.
        # Then clearing will be the exception.

        if len(args) == 0:
            print("Unable to load assets without knowing the source file. Try:")
            print("   > python manage.py clear_and_add_by_asset [filename] [list of asset types]")
            print("Here the list of asset types is optional. Without that list, this command")
            print("will default to iterating over all types in the source file, sequentially")
            print("clearing and uploading them.")
            return
        else:
            file_name = os.path.join(settings.BASE_DIR, args[0])

            with open(file_name) as f:
                dr = csv.DictReader(f)
                source_asset_types = list(set([row['asset_type'] for row in dr]))


            if len(args) > 1:
                chosen_asset_types = args[1:]
            else:
                chosen_asset_types = source_asset_types
                if not override_clearing:
                    raise ValueError(f"Are you really sure you want to clear all these asset types ({chosen_asset_types})? If so, comment out this exception (or just list them when invoking the command).")
            print(f"chosen_asset_types = {chosen_asset_types}")

            for t in source_asset_types:
                if re.search('\|', t) is not None and t in chosen_asset_types:
                    print(f"Whoa! Whoa! What are we going to do with an asset of type {t}?")
                    raise ValueError("Whoa! Whoa! What are we going to do with an asset of type {t}?")

            # Get existing types
            extant_types = [a.name for a in AssetType.objects.all()]

            new_types = []
            for t in chosen_asset_types:
                if t not in extant_types:
                    new_types.append(t)
            print(f"New types in the source file that are not currently in the database: {new_types}")

            print(f"About to start{'' if override_clearing else 'cleaning and'} uploading {chosen_asset_types}.")

            total_count = 0

            for asset_type in chosen_asset_types:
                type_count = 0
                with open(file_name) as f:
                    dr = csv.DictReader(f) # This file needs to be reopened to refresh the dr iterator (used up in the loop below).

                    ## Clear the assets of this type if any are found in the database. ##
                    if not override_clearing:
                        if asset_type in extant_types:
                            selected_assets = Asset.objects.filter(asset_types__name=asset_type)
                            if len(selected_assets) > 0:
                                print(f"Clearing all {len(selected_assets)} assets with type '{asset_type}'.")
                                selected_assets.delete()
                            else:
                                print(f"No assets with type '{asset_type}' found.")

                    ## Upload the new assets. ##
                    for row in dr:
                        # get or create a new org
                        if row['asset_type'] == asset_type:
                            organization, organization_created = Organization.objects.get_or_create(
                                name=non_blank_value_or_none(row, 'organization_name'),
                                defaults={
                                    'email': non_blank_value_or_none(row, 'organization_email'),
                                    'phone': standardize_phone(row['organization_phone'])
                                }
                            )

                            if not organization_created:
                                if organization.email is None:
                                    organization.email = non_blank_value_or_none(row, 'email')
                                #else:
                                # Since this is an EmailField, it's not so easy to just list all the options as the new field value.

                                if organization.phone is None and 'organization_phone' in row:
                                    organization.phone = standardize_phone(row['organization_phone'])
                                #else:
                                # Since this is a PhoneNumberField, it's not so easy to just list all the options as the new field value.

                            organization.save()
                            # END primitive Organization object handling

                            location, location_created = update_or_create_location(row)

                            asset_types = [AssetType.objects.get_or_create(name=asset_type)[0] for asset_type in
                                           parse_cell(row['asset_type'])] if row['asset_type'] else []

                            tags = [Tag.objects.get_or_create(name=tag)[0] for tag in
                                    parse_cell(row['tags'])] if row['tags'] else []

                            services = [ProvidedService.objects.get_or_create(name=service)[0] for service in
                                        parse_cell(row['services'])] if 'services' in row else []

                            hard_to_count_pops = [TargetPopulation.objects.get_or_create(name=pop)[0] for pop in
                                                  parse_cell(row['hard_to_count_population'])] \
                                if 'hard_to_count_population' in row else []

                            data_source = DataSource.objects.get_or_create(
                                name=non_blank_value_or_none(row, 'data_source_name'),
                                defaults={'url': row['data_source_url']})[0] if row['data_source_name'] else None

                            asset = Asset.objects.create(
                                name=non_blank_value_or_none(row, 'name'),
                                localizability=get_localizability(non_blank_value_or_none(row, 'localizability')),

                                url=non_blank_value_or_none(row, 'url'),
                                email=non_blank_value_or_none(row, 'email'),
                                phone=standardize_phone(row['phone']),

                                hours_of_operation=non_blank_value_or_none(row, 'hours_of_operation'),
                                holiday_hours_of_operation=non_blank_value_or_none(row, 'holiday_hours_of_operation'),
                                periodicity=non_blank_value_or_none(row, 'periodicity'),
                                capacity=non_blank_type_or_none(row, 'capacity', int),
                                wifi_network=non_blank_value_or_none(row, 'wifi_network'),
                                wifi_notes=non_blank_value_or_none(row, 'wifi_notes'),

                                etl_notes=non_blank_value_or_none(row, 'notes'),

                                child_friendly=boolify(non_blank_value_or_none(row, 'child_friendly')),
                                internet_access=boolify(non_blank_value_or_none(row, 'internet_access')),
                                computers_available=boolify(non_blank_value_or_none(row, 'computers_available')),
                                accessibility=boolify(non_blank_value_or_none(row, 'accessibility')),
                                open_to_public=boolify(non_blank_value_or_none(row, 'open_to_public')),
                                sensitive=boolify(non_blank_value_or_none(row, 'sensitive')),
                                do_not_display=boolify(non_blank_value_or_none(row, 'do_not_display')),

                                location=location,
                                organization=organization,
                                data_source=data_source,
                                primary_key_from_rocket=non_blank_value_or_none(row, 'primary_key_from_rocket'),
                                synthesized_key=non_blank_value_or_none(row, 'synthesized_key'),
                            )

                            asset.asset_types.set(asset_types)
                            asset.tags.set(tags)
                            asset.services.set(services)
                            asset.hard_to_count_population.set(hard_to_count_pops)
                            asset.save()
                            type_count += 1
                            total_count += 1
                            print('Created', asset)
                print(f"Created {type_count} assets of type {asset_type}.")
            print(f"Created a total of {total_count} assets.")

