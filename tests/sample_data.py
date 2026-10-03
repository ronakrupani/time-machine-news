"""Trimmed copies of real loc.gov responses."""

SEARCH_RESPONSE = {
    "pagination": {"of": 191, "current": 1, "perpage": 2},
    "results": [
        {
            "date": "1912-04-19",
            "description": [
                "Titanic Meets Terrible Disaster1350 Lives Lost World Largest Ship Goes Down Strikes Iceberg"
            ],
            "id": "http://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2",
            "image_url": [
                "https://tile.loc.gov/image-services/iiif/service:ndnp:mthi:batch_mthi_graywolf_ver01:data:sn86075094:00295860935:1912041901:0135/full/pct:6.25/0/default.jpg#h=442&w=310",
                "https://tile.loc.gov/text-services/word-coordinates-service?segment=/x.xml&format=alto_xml",
            ],
            "location_city": ["roundup"],
            "location_state": ["montana"],
            "number_edition": ["1"],
            "number_lccn": ["sn86075094"],
            "number_page": ["0000000002"],
            "partof_title": ["the roundup record (roundup, mont.) 1908-1929"],
            "title": "Image 2 of The roundup record (Roundup, Mont.), April 19, 1912",
            "url": "https://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2&q=titanic",
        },
        {
            "date": "1913-06-08",
            "description": ["EXTRA headline text"],
            "id": "http://www.loc.gov/resource/sn89053729/1913-06-08/ed-1/?sp=1",
            "image_url": [],
            "location_state": ["georgia"],
            "number_lccn": ["sn89053729"],
            "title": "Image 1 of Atlanta Georgian (Atlanta, Ga.), June 8, 1913, (EXTRA)",
        },
    ],
}

TITLES_RESPONSE = {
    "pagination": {"of": 118},
    "results": [
        {
            "title": "Great Falls Daily Tribune (Great Falls, Mont.) 1895-1921",
            "number_lccn": ["sn85042379"],
            "location_city": ["great falls"],
            "location_state": ["montana"],
            "date": "1895",
            "description": ["Daily"],
            "url": "https://www.loc.gov/item/sn85042379/",
        }
    ],
}

RESOURCE_RESPONSE = {
    "cite_this": {
        "chicago": "<cite>The Roundup Record</cite>. (Roundup, MT), Apr. 19 1912. https://www.loc.gov/item/sn86075094/1912-04-19/ed-1/."
    },
    "pagination": {"of": 8},
    "resource": {
        "fulltext_file": "https://tile.loc.gov/text-services/word-coordinates-service?segment=/service/ndnp/mthi/batch_mthi_graywolf_ver01/data/sn86075094/00295860935/1912041901/0135.xml&format=alto_xml&full_text=1",
        "image": "https://tile.loc.gov/image-services/iiif/service:ndnp:mthi:batch_mthi_graywolf_ver01:data:sn86075094:00295860935:1912041901:0134/full/pct:6.25/0/default.jpg",
        "pdf": "https://tile.loc.gov/storage-services/service/ndnp/mthi/batch_mthi_graywolf_ver01/data/sn86075094/00295860935/1912041901/0135.pdf",
    },
}

FULLTEXT_RESPONSE = {
    "/service/ndnp/mthi/batch_mthi_graywolf_ver01/data/sn86075094/00295860935/1912041901/0135.xml": {
        "full_text": "Titanic Meets Terrible\nDisaster-1350 Lives Lost\n\n\nSinking of Titanic, world's great-\nest vessel, on maiden voyage across At\nlantic."
    }
}
