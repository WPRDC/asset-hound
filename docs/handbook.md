## Operational Handbook for the Asset Map + Database

The objective of this project is to join many datasets from federal, state, and local sources to synthesize a comprehensive picture of the assets that make up the infrastructure of a particular community.

### Source-file preparation
We assembled many such datasets, in some cases filtering them down to just those in Allegheny County, or even filtering into several different files, one for each of the types of assets in the original file.

The source files can be found in [this private repository](https://github.com/WPRDC/liquid-assets). Source files are typically either CSV files, Excel files (which are then converted to CSV files using Visidata), or ESRI shapefiles (which are converted to SQLite using [shapefile-to-sqlite](https://pypi.org/project/shapefile-to-sqlite/), and from there to CSV, again by Visidata).

### Conversion to a standard schema
[This ETL script](https://github.com/WPRDC/rocket-etl/blob/master/engine/payload/asset_map/_facet_hound.py) can be run (after setting the parameter `one_file` to `True`) to process all the source files represented in the `job_dicts` list, using the corresponding schemas, to produce an `all_assets.csv` file, which contains all the asset information in a standard schema, suitable for uploading to the asset database. This command will process all the source files:

```> python launchpad.py engine/payload/asset_map/_facet_hound.py mute``` 

The job codes defined in the `job_dicts` list can be supplied as command-line arguments to generate a file containing just those assets. For instance, the `job_code` value for the public-art dataset is `public_art`, so running

```> python launchpad.py engine/payload/asset_map/_facet_hound.py mute public_art```
will only process the public_art job. If `one_file == False`, the generated file will be called `public-art-pgh.csv` and will only contain the fields defined by the corresponding schema (whereas when `one_file == True`, all fields in the asset schema are included in the file). All converted files will be saved to the directory given in the variable `ASSET_MAP_PROCESSED_DIR`, as specified by the `destination_file` parameter in the jobs (though this could be changed).

The contents of these files are considered to be raw assets.

### Uploading raw assets to the asset database and then downloading them

The asset database (defined in [this Django models.py file](https://github.com/WPRDC/asset-hound/blob/master/assets/models.py)) has a RawAsset model which is compatible with the schema produced by the `_facet_hound.py` ETL job. To upload a file of raw assets, converted by `_facet_hound.py`, move the file to the assets server (`> scp all_assets.csv <username>@assets.wprdc.org:<path-to-asset_hound>/raw_assets_to_add.csv`), shell into the Django server, change directories to the Django directory, activate the Django virtual environment (`source env/bin/activate`), and run the RawAsset-loading management command (`> python manage.py load_raw_assets raw_assets_to_add.csv`).

The contents of the raw-asset table can then be exported from the database by running
```> python manage.py dump_raw_assets```

(Note that load_raw_assets.py currently supports inserts but not yet upserts/updates because the required Asset changes (including reapplying old edits) need to be coded first. The `synthesized_key` field must be unique to each raw asset. This constraint is currently enforced by the `load_raw_assets` management command.)

### Creating and editing assets
The resulting `raw_asset_dump.csv` file is then exported to another computer, where a subset of raw assets may be selected (for instance, all raw assets of a given asset-type (like `restaurants`)). This filtered file is run through a Python script that facilitates finding and merging raw assets. When the script finds sufficiently similar raw assets, it proposes them as duplicates to merge and the lets the user select among conflicting values on a field-by-field basis. The output of this process is what we call a merge-instructions file.

#### The deduplication process
Since the data for the asset map comes from many different sources, inevitably there are duplicates entries of the same asset. To find and merge the duplicates, a group of assets are run through a Python script. The script first parses the addresses of all the assets using the `usaddress` package and then standardizes the parsed addresses. An example of this is changing "Street" and "St." to "St". Next, the code goes asset by asset and attempts to find other assets with a matching
street number, street name, and ZIP code. If a match is found, a fuzzy string match is done on the asset names. If they are not similar, meaning they are not the same asset (ex. "Starbucks" and "Piada"), then their geocoordinates are checked for a match. If they don’t match, the assets are not merged or flagged for review. If they are exact matches, they are not merged but flagged for review. This flag was useful when assets at the same location would overlap each other on the
map, however, now assets at the same geocoordinates are offset so all are visible. If the fuzzy string match returns a possible match but not a nearly exact one, the assets are not processed as duplicates, but they are flagged for manual review to determine if they are truly duplicates.

If the fuzzy string match determines that the asset names are almost identical or identical, then the assets are processed as duplicates. The process begins by having the user choose a "primary entry", or one that will hold all the merged values for the set of duplicates. If the names of the duplicates are not identical, the user chooses the correct name for the asset. The script then checks each field for missing or conflicting values. For example, when checking the phone number field on a set of two duplicate assets, if one entry does not have a phone number but the other does, then the one existing phone number is written to the primary entry. If the entries have two different phone numbers, this is printed out in the console and the user is asked to either pick a correct phone number to write to the primary entry, or to flag the set of duplicates for later review.

Once the set of duplicates finishes the merging process, the primary entry is written to a new CSV file as a "merge-instructions" file that will be the output file at the end of the code. If there was no duplicate for an asset, once this is determined the asset is immediately written to the merge-instructions file. Once the merge-instructions file is complete, it is saved to the user's workspace.

#### The merge-instructions file
The merge-instructions file is a CSV file that is the output of the deduplicating Python script. This file contains all the same fields as the original file of assets before being run through the deduplicating Python script, with the addition of an `ids_to_merge` field. This field indicates to the Asset updater which assets should be updated. 

If an asset does not have a duplicate, its own id is used in the `ids_to_merge` field. This allows for assets without duplicates to still be updated if needed.

If an asset has one or more duplicates, in the primary entry with the most up-to-date information about the asset, all of the `id`s of the duplicates are written to the `ids_to_merge` field joined by `+` symbols. This indicates to the Asset updater which duplicate assets are being merged.

Additionally, the merge-instructions file has a `flags` field. During the deduplication process, the user can write something into the `flags` field for assets needing manual review. This field is helpful to the user, but ignored by the Asset updater.

### Updating Assets
Records in the Assets table can be modified in three ways: 1) Using the Django admin interface allows record-level modifications. This is fine for handling a few changes, but inefficient for bulk changes. 2) Making changes through the Django shell. This requires shelling into the assets server and making changes with Python commands. This can be powerful and fast but also tricky and unforgiving, requiring the user to manually take care of many things, and it only leaves documentation in the form of the history-tracking model. 3) The Asset updater, a web service that accepts merge-instructions files, allows them to be validated, automates much of the process, and tags any Asset edits with an identifiable "change_reason" field.

There are two different versions of the Asset updater. The original version uses merge instructions generated from a raw-asset dump file. 

[https://assets.wprdc.org/edit/update-assets/using-raw-assets/](https://assets.wprdc.org/edit/update-assets/using-raw-assets/)

This can be used to link one or more RawAssets to a new or existing Asset (where the Asset table is what is used to generate the asset map and to give details about the asset when the corresponding dot in the map is clicked) and to set the field values of that Asset. New Location and Organization instances can also be created through this process, as described on the [Asset updater page](https://assets.wprdc.org/edit/update-assets/using-raw-assets/).

The [Asset-based Asset updater](https://assets.wprdc.org/edit/update-assets/using-assets/) has similar functionality, but its merge-instructions file is generated from an asset dump file, which tells the updater which Assets how to edit Assets and how to merge existing Assets into existing Asset instances. When multiple Assets are merged into one, the others are "delisted", which means that their `do_not_display` value is set to `True`. The delisted Assets have their RawAssets reassigned to the single Asset that the others are merged into.

#### More about delisting
It is also the case that whenever an Asset is saved with no RawAssets pointing to it, it is automatically considered an unsupported Asset and therefore delisted. Delisting prevents an Asset from appearing on the map, but still allows it to persist in the database. Delisted Assets fall into two categories: 1) Those that have been delisted because they are not supported by links to any RawAssets. (These could in principle be deleted at some point, as could any orphaned Location or Organization instances that are not linked to any Assets.) 2) Those that are being hidden because we don't currently wish to show them (such as Assets outside of Allegheny County), but which we may wish to revive at some point (if we expand the map beyond Allegheny County). 

In contrast with Assets, RawAssets should normally not be deleted (or mutated) since they are a representation of the source file. If a RawAsset were deleted and then an update to the source data resulted in records being reuploaded as RawAssets, a RawAsset that had previously been set to not display could finds its way back on to the map. In principle, Assets that we wish to remove from the map could be deleted and their RawAssets set to `do_not_display = True`, but the approach that seems a more natural fit for our current workflow is to maintain the Asset (including its links to the RawAssets) but delist the Asset.

### Example workflow for adding a new file containing assets to the assets database
1) Convert the source file to a CSV file.
2) Edit a copy of [this ETL script](https://github.com/WPRDC/rocket-etl/blob/master/engine/payload/asset_map/_facet_hound.py) to add a schema and a `job_dict` entry in the `job_dicts` list. These specify how the fields in the source file map to the common asset-map schema. A `job_code` value should be given in the schema to allow the job (that is, the particular task of transforming the source file into another CSV file representing a particular set of assets) to be named from the command-line.
3) Set `one_file` to be `False` in the script.
4) Run the job like this: `> python ../../../launchpad.py asset_map/_facet_hound.py mute <job_code>`
5) A generated file with a name you provide (we'll suppose it's `new_assets.csv`) in the `job_dicts` entry should show up in the `processed` directory.
6) Transfer this file to the asset-map server (e.g., `> scp new_raw_assets.csv <your_username>@assets.wprdc.org:<path-where-you're-trying-to-put-the-file>`
7) Change to the asset-map backend directory and move the `new_raw_assets.csv` file there.
8) Run `> source env/bin/activate` to activate the virtual environment that supports Django.
9) Run `> python manage.py load_raw_assets new_raw_assets.csv` to load the raw assets into the database.
10) Run `> python manage.py dump_raw_assets` to dump the raw assets to a `raw_asset_dump.csv` file suitable for generating merge-instructions from.

### Adding new asset types
Each asset should be associated with exactly one asset type. (The model supports multiple asset types per asset, but we've set as a policy limiting each asset to one type. One reason for this is that the map does not have a way of representing a multi-type asset. Another reason is that, in practice, multi-type assets may have conflicts between the details for each type (e.g., a day-care center and a school in the same building, under the same organization, but with different operating hours and phone numbers).)

When new assets are added (through a management command or the Asset updater) that are coded with a previously unused type, a corresponding new AssetType instance will be created in the database. However, this AssetType has two fields which need to be set manually through the Django admin interface: title (usually just a readable, capitalized version of the AssetType name) and category (which can be picked from a drop-down list of Category instances). If these fields are specified after the creation of Assets, the Assets will need to be re-synced to Carto so that they appear on the map correctly. This may be done by running the `sync_to_carto` management command or by resaving the Assets (e.g. through the Django admin interface or by rerunning the Asset updater).

### Exporting data
Accessing the URL [https://assets.wprdc.org/edit/dump_assets/](https://assets.wprdc.org/edit/dump_assets/) triggers a dump of the assets which will show up `(# of records)/(4000/minute)` later at
[https://assets.wprdc.org/asset_dump.csv](https://assets.wprdc.org/asset_dump.csv).

There is also a cronjob which periodically dumps the full set of assets to this file. This file is used as the source for the ETL job controlled by [this script](https://github.com/WPRDC/rocket-etl/blob/master/engine/payload/wprdc/assets_to_ckan.py), which runs nightly on the tools server.

### Carto integration
While there are REST API endpoints provided by the Django REST Framework, the server/database/API combination takes too long to pull the data for all assets to be used to supply data to the map on the frontend. Our current solution is to keep a narrow version of the assets table on Carto (with the important fields being asset name, asset type, category, latitude, longitude, `the_geom`, and `the_geom_webmercator`). This table is just a cache that fuels the map part of the frontend. When a user clicks on an asset marker on the front end, the assets database is queried to fill in the grey box with further details about the asset (like street address).

The entire assets database can be pushed to the Carto database by running a management command:

```> python manage.py sync_to_carto```

Individual asset types may be specified as command-line arguments to update just those asset types:

```> python manage.py sync_to_carto restaurants coffee_shops```

Also, the Asset save function has been modified to include a step wherein the corresponding row in the Carto table is updated/inserted/deleted, as appropriate. This involves four API calls (one to check whether the Asset ID already exists in the Carto table), one to do the updating/inserting/deleting, and two to update the geofields (since Carto does not automatically update the `the_geom` and `the_geom_webmercator` fields, but doing so is essential for updating the location of the map point. While this slows down Asset saves, it keeps the Carto map up-to-date and facilitates edits.

While this covers all Asset saves (and therefore all changes made through the Asset updater), changes made to a Location instance through the Django admin interface or Django shell will not currently trigger an updating of the Carto table. To cover these cases, the `sync_to_carto` management command is set to run daily at 1am, to entirely refresh the Carto table.

Since maybe Assets share Locations and would otherwise overlap, rendering all but one normally hidden on the map, one step in the Carto integration is to spatially distinguish these Assets by offsetting their markers slightly (~20 feet) in different directions.

A useful endpoint for testing Carto integration is this kind of record-level query: [https://wprdc.carto.com/api/v2/sql?q=select%20*%20from%20wprdc.assets_v1%20where%20id%20=%20206603](https://wprdc.carto.com/api/v2/sql?q=select%20*%20from%20wprdc.assets_v1%20where%20id%20=%20206603)

*Possible performance improvements:* Carto inserts are being done in batches as large as 100. Carto updates are being performed singly, but they could be rewritten to also be done in batches. Possibly experiment with adding Carto integration to Location saves.

#### Task queue
Because all the web requests needed to process the Carto integration add up when the Asset updater is asked to process many edits, handling these requests synchronously can cause the Asset updater web requests to time out. To avoid this, the Asset saves are done with a flag that overrides immediate Carto synchronization, and the modified IDs are processed asynchronously, by sending them to [Huey](https://huey.readthedocs.io/en/latest/) (a minimal task queue with built-in Django support).

To actiate the Huey consumer (the process that watches for the addition of tasks to the queue and executes them), run the `start_huey.sh` script in the Django project directory as root (`> sudo start_huey.sh`). At present, this is just running in a tmux session, but eventually it will be configured to run automatically under `supervisor`, using the configuring given [here](https://www.untangled.dev/2020/07/01/huey-minimal-task-queue-django/).

