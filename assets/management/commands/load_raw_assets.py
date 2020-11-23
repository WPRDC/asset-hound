import csv
import os
import re
import sys  # This is a workaround for an error that
csv.field_size_limit(sys.maxsize)  # looks like this:
# _csv.Error: field larger than field limit (131072)

import phonenumbers
from django.conf import settings
from django.core.management.base import BaseCommand

from assets.models import (RawAsset,
                           Asset,
                           AssetType,
                           Tag,
                           ProvidedService,
                           TargetPopulation,
                           DataSource)

from assets.management.commands.util import parse_cell, get_localizability, boolify, standardize_phone
from assets.management.commands.clear_and_load_by_type import non_blank_value_or_none, non_blank_type_or_none

from pprint import pprint

class Command(BaseCommand):
    help = 'Loads raw assets from a CSV file, which may be specified by a command-line argument.'

    def add_arguments(self, parser): # Necessary boilerplate for accessing args.
        parser.add_argument('args', nargs='*')

    def handle(self, *args, **options):

        clear_first = False # Usually we don't want to clear RawAssets when loading them.

        if len(args) == 0:
            print("Unable to load assets without knowing the source file. Try:")
            print("   > python manage.py load_raw_assets [filename] [list of asset types]")
            print("Here the list of asset types is optional. Without that list, this command")
            print("will default to iterating over all types in the source file, sequentially")
            print("uploading them (clearing them before uploading if clear_first = True).")
            return
        else:
            # Get existing types
            chosen_asset_types = []
            extant_types = [a.name for a in AssetType.objects.all()]
            for arg in args:
                if arg == 'clear_first':
                    clear_first = True
                elif arg in extant_types:
                    chosen_asset_types.append(arg)

            file_name = os.path.join(settings.BASE_DIR, args[0])

            with open(file_name) as f:
                dr = csv.DictReader(f)
                source_asset_types = list(set([row['asset_type'] for row in dr]))

            if chosen_asset_types == []:
                chosen_asset_types = source_asset_types
                if clear_first:
                    raise ValueError(f"Are you really sure you want to clear all these asset types ({chosen_asset_types})? If so, comment out this exception (or just list them when invoking the command).")
            print(f"chosen_asset_types = {chosen_asset_types}")

            for t in source_asset_types:
                if re.search('\|', t) is not None and t in chosen_asset_types:
                    print(f"Whoa! Whoa! What are we going to do with an asset of type {t}?")
                    raise ValueError("Whoa! Whoa! What are we going to do with an asset of type {t}?")

            new_types = []
            for t in chosen_asset_types:
                if t not in extant_types:
                    new_types.append(t)
            print(f"New types in the source file that are not currently in the database: {new_types}")

            print(f"About to start{'' if not clear_first else 'cleaning and'} uploading {chosen_asset_types}.")

            total_count = 0

            for asset_type in chosen_asset_types:
                type_count = 0
                with open(file_name) as f:
                    dr = csv.DictReader(f) # This file needs to be reopened to refresh the dr iterator (used up in the loop below).

                    if clear_first:
                        ## Clear the assets of this type if any are found in the database. ##
                        if asset_type in extant_types:
                            selected_assets = RawAsset.objects.filter(asset_types__name=asset_type)
                            if len(selected_assets) > 0:
                                print(f"Clearing all {len(selected_assets)} assets with type '{asset_type}'.")
                                selected_assets.delete()
                            else:
                                print(f"No assets with type '{asset_type}' found.")

                    ## Upload the raw assets. ##
                    keep_links = True

                    mode = 'insert'
                    if mode in ['upsert', 'update']:
                        raise ValueError(f"load_raw_assets.py does not yet support upserts/updates because the Asset changes (including reapplying old edits) needs to be coded first.")
                    for row in dr:
                        if row['asset_type'] == asset_type:
                            if mode == 'insert':
                                # Verify that Asset with matching keys does not already exist.
                                assert 'synthesized_key' in row
                                assert row['synthesized_key'] != ''
                                queryset = RawAsset.objects.filter(synthesized_key=row['synthesized_key'])
                                if len(queryset) > 0:
                                    raise ValueError(f"Unable to {mode} row with synthesized key {row['synthesized_key']} because one or more other such rows exist (with IDs {[r['id'] for r in queryset]}.")
                                if 'primary_key_from_rocket' in row and row['primary_key_from_rocket'] not in ['', None]:
                                    queryset = RawAsset.objects.filter(primary_key_from_rocket=row['primary_key_from_rocket'])
                                    if len(queryset) > 0:
                                        raise ValueError(f"Unable to {mode} row with primary_key_from_rocket {row['primary_key_from_rocket']} because one or more other such rows exist (with IDs {[r['id'] for r in queryset]}.")
                                asset_to_link_to = None
                            #elif mode in ['update', 'upsert']:
                                # Try to find existing RawAssets based on primary_key_from_rocket (or failing that synthesized_key).
                                # Or maybe find based on sythesized_key but try to validate with primary key.
                                # asset_to_link_to =


                            #if keep_links:
                            #    # Try to identify which existing Asset this RawAsset should be linked to
                            #    # based on the synthesized_key value.
                            #    assert 'synthesized_key' in row
                            #    assert row['synthesized_key'] != ''
                            #    queryset = Asset.objects.filter(synthesized_key=row['synthesized_key'])
                            #    if len(queryset) == 1:
                            #        asset_to_link_to = queryset[0]
                            #    elif len(queryset) > 2:
                            #        raise ValueError(f"{len(queryset)} possible Asset links found for synthesized key = {row['synthesized_key']}")
                            #    else:
                            #        print(f"Unable to find an Asset with synthesized_key = {row['synthesized_key']}")
                            #else:
                            #    asset_to_link_to = None

                            print(f"asset_to_link_to = {asset_to_link_to}")
                            # Since the next line uses get_or_create, it will create new asset types, without insisting that they
                            # be manually entered (along with a Category). Without the Category, a dot representing this type
                            # of assets will not appear on the map.
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
                                defaults={'url': non_blank_value_or_none(row, 'data_source_url')})[0] if row['data_source_name'] else None


                            print("See: All this currently does is create new RawAssets not update existing ones.")
                            print("Consider adding a mandatory insert/update/upsert command-line argument.")

                            raw_asset = RawAsset.objects.create(
                                asset = asset_to_link_to,
                                name=non_blank_value_or_none(row, 'name'),
                                localizability=get_localizability(non_blank_value_or_none(row, 'localizability')),

                                url=non_blank_value_or_none(row, 'url'),
                                email=non_blank_value_or_none(row, 'email'),
                                phone=standardize_phone(row.get('phone', None)),

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

                                street_address = non_blank_value_or_none(row, 'street_address'),
                                city = non_blank_value_or_none(row, 'city'),
                                state = non_blank_value_or_none(row, 'state'),
                                zip_code = non_blank_value_or_none(row, 'zip_code'),
                                parcel_id = non_blank_value_or_none(row, 'parcel_id'),
                                residence = boolify(non_blank_value_or_none(row, 'residence')),
                                available_transportation = non_blank_value_or_none(row, 'location_transportation'),
                                parent_location = non_blank_value_or_none(row, 'parent_location'),
                                # Note that parent_location has not yet been added to the Assets (since
                                # the original loader didn't do this), so now it's being added to RawAssets
                                # as a string, representing the name of the location.

                                # The thing about the parent location is that it's just a name in the
                                # source data at this point, and we've got to figure out how we're going
                                # to connect it to Location instances. At present, there are only 153 distinct
                                # parent_location values, so doing it semimanually seems viable.
                                # It's pretty much the same deal with the organization having a
                                # Location instance. It might eventually make sense to make this
                                # association, but there's no data or wiring or front-end features
                                # to support it at this point.
                                latitude = non_blank_type_or_none(row, 'latitude', float),
                                longitude = non_blank_type_or_none(row, 'longitude', float),
                                #geom =  We're still not uploading the geom field yet because it wasn't
                                # in the sample_assets.csv field used to populate the Asset model.
                                # There are only a few features with useful geom values (boundaries of
                                # parks mostly), and those will be handled later, once the front end
                                # is ready to use those values.
                                geocoding_properties = non_blank_value_or_none(row, 'geocoding_properties'),

                                organization_name = non_blank_value_or_none(row, 'organization_name'),
                                organization_email = non_blank_value_or_none(row, 'organization_email'),
                                organization_phone = standardize_phone(row.get('organization_phone', None)),

                                data_source=data_source,
                                primary_key_from_rocket=non_blank_value_or_none(row, 'primary_key_from_rocket'),
                                synthesized_key=non_blank_value_or_none(row, 'synthesized_key'),
                            )

                            raw_asset.asset_types.set(asset_types)
                            raw_asset.tags.set(tags)
                            raw_asset.services.set(services)
                            raw_asset.hard_to_count_population.set(hard_to_count_pops)
                            raw_asset.save()
                            type_count += 1
                            total_count += 1
                            print('Created', raw_asset)
                print(f"Created {type_count} raw assets of type {asset_type}.")
            print(f"Created a total of {total_count} assets.")

