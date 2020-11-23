import os, csv, re

from django.conf import settings
from django.core.management.base import BaseCommand

from assets.models import RawAsset, Asset, AssetType


def to_dict_for_csv(asset: Asset):
    return {
        'id': asset.id,
        'name': asset.name,
        'asset_type': '|'.join([getattr(t, 'name', 'None') for t in asset.asset_types.all()]),
        'raw_asset_ids': '|'.join([str(r.id) for r in asset.rawasset_set.all()]), # This is one field that differs from the RawAsset dump.
        'tags': '|'.join([getattr(t, 'name', 'None') for t in asset.tags.all()]),
        'location_id': getattr(asset.location, 'id', None),
        'street_address': getattr(asset.location, 'street_address', None),
        'unit': getattr(asset.location, 'unit', None),
        'unit_type': getattr(asset.location, 'unit_type', None),
        'municipality': getattr(asset.location, 'municipality', None),
        'city': getattr(asset.location, 'city', None),
        'state': getattr(asset.location, 'state', None),
        'zip_code': getattr(asset.location, 'zip_code', None),
        'latitude': getattr(asset.location, 'latitude', None),
        'longitude': getattr(asset.location, 'longitude', None),
        'parcel_id': getattr(asset.location, 'parcel_id', None),
        'residence': getattr(asset.location, 'residence', None),
        'iffy_geocoding': getattr(asset.location, 'iffy_geocoding', None),
        'available_transportation': getattr(asset.location, 'available_transportation', None),
        'parent_location_id': getattr(getattr(asset.location, 'parent_location', None), 'id', None),
        'parent_location': getattr(asset.location, 'parent_location', None),
        'url': asset.url,
        'email': asset.email,
        'phone': asset.phone,
        'hours_of_operation': asset.hours_of_operation,
        'holiday_hours_of_operation': asset.holiday_hours_of_operation,
        'periodicity': asset.periodicity,
        'capacity': asset.capacity,
        'wifi_network': asset.wifi_network,
        'wifi_notes': asset.wifi_notes,
        'internet_access': asset.internet_access,
        'computers_available': asset.computers_available,
        'accessibility': asset.accessibility,
        'open_to_public': asset.open_to_public,
        'child_friendly': asset.child_friendly,
        'localizability': asset.localizability,
        'sensitive': asset.sensitive,
        'do_not_display': asset.do_not_display,
        'services': '|'.join([getattr(s, 'name', None) for s in asset.services.all()]),
        'hard_to_count_population': '|'.join([getattr(p, 'name', 'None') for p in asset.hard_to_count_population.all()]),
        'data_source_names': '|'.join([getattr(r.data_source, 'name', 'None') for r in asset.rawasset_set.all()]), # Another field that differs from the RawAsset dump.
        'data_source_urls': '|'.join([getattr(r.data_source, 'url', 'None') for r in asset.rawasset_set.all()]), # Another field that differs from the RawAsset dump.
        'organization_name': getattr(asset.organization, 'name', ''),
        'organization_phone': getattr(asset.organization, 'phone', ''),
        'organization_email': getattr(asset.organization, 'email', ''),
        'etl_notes': asset.etl_notes,
        #'primary_key_from_rocket': asset.primary_key_from_rocket,
        #'synthesized_key': asset.synthesized_key,
        'geocoding_properties': getattr(asset.location, 'geocoding_properties', None),
    }


class Command(BaseCommand):
    help = 'Dump assets to a CSV file, with the option to specify one or more asset types as command-line arguments.\n\nUsage:\n> python manage.py dump_assets_by_type <asset_type>'

    def add_arguments(self, parser): # Necessary boilerplate for accessing args.
        parser.add_argument('args', nargs='*')

    def handle(self, *args, **options):
        filepath = None
        filename = 'asset_dump.csv'
        extant_asset_types = [a.name for a in AssetType.objects.all()]
        chosen_asset_types = []
        for arg in args:
            if arg in extant_asset_types:
                chosen_asset_types.append(arg)
            elif re.match('/home/david/downloads', arg) is not None and os.path.isdir('/'.join(arg.split('/')[:-1])):
                filepath = arg
            else:
                print(f"It is not clear what to with this argument: '{arg}'.")

        if len(chosen_asset_types) > 0:
            print(f"Dumping just the assets of type {chosen_asset_types[0]}.")
            assets_iterator = Asset.objects.filter(asset_types__name = chosen_asset_types[0])
            filename = f'asset_dump_{chosen_asset_types[0]}.csv'
        else:
            print("Dumping all assets.")
            assets_iterator = Asset.objects.all()

        if filepath is None:
            output_file = os.path.join(settings.BASE_DIR, filename)
        else:
            output_file = filepath

        with open(output_file, 'w') as f:
            writer = csv.DictWriter(
                f,
                ['id',
                 'name',
                 'asset_type',
                 'raw_asset_ids', # Replaces asset_id in raw asset dump.
                 'tags',
                 'location_id', # Not present in raw asset dump.
                 'street_address',
                 'unit',
                 'unit_type',
                 'municipality',
                 'city',
                 'state',
                 'zip_code',
                 'latitude',
                 'longitude',
                 'parcel_id',
                 'residence',
                 'iffy_geocoding',
                 'available_transportation',
                 'parent_location_id',
                 'parent_location',
                 'url',
                 'email',
                 'phone',
                 'hours_of_operation',
                 'holiday_hours_of_operation',
                 'periodicity',
                 'capacity',
                 'wifi_network',
                 'wifi_notes',
                 'internet_access',
                 'computers_available',
                 'accessibility',
                 'open_to_public',
                 'child_friendly',
                 'sensitive',
                 'do_not_display',
                 'localizability',
                 'services',
                 'hard_to_count_population',
                 'data_source_names',
                 'data_source_urls',
                 'organization_name',
                 'organization_phone',
                 'organization_email',
                 'etl_notes',
                 #'primary_key_from_rocket', # Excluded from asset dump.
                 #'synthesized_key', # Excluded from asset dump.
                 'geocoding_properties',
                 ],
            )
            writer.writeheader()
            for k,asset in enumerate(assets_iterator.iterator()): # Use the "iterator()" method to lazily evaluate the query in chunks (to save memory)
                writer.writerow(to_dict_for_csv(asset))
                if k % 2000 == 2000-1:
                    print(f"Wrote {k+1} raw assets so far.")
