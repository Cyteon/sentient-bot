# This project is licensed under the terms of the GPL v3.0 license. Copyright 2024 Cyteon

from __future__ import annotations

from dataclasses import dataclass

from typing import Final

def user_global_data_template(user_id):
    return {
        "id": user_id,
        "opinion": ""
    }

def self_data_template():
    return {
        "personality": "",
        "opinions": "",
        "relations": {}
    }
