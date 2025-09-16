"""Utils for dataset manipulation."""


def get_base_json() -> str:
    """Base json for a cut."""
    return """{
  "team1": "Team1",
  "team2": "Team2",
  "dir": "",
  "files" : [],
  "filename" : "",
  "verified" : false,
  "training" : true,
  "labeled": true,
  "rendered_file": false,
  "game_mode": "",
  "cuts": [
  ],

  "Warnings": [
  ]
}"""
