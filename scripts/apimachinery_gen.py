import re
import httpx
import json

def fetch_swagger_schema():
    url = "https://raw.githubusercontent.com/kubernetes/kubernetes/refs/tags/v1.31.4/api/openapi-spec/swagger.json"
    response = httpx.get(url)
    response.raise_for_status()
    return response.json()

def process_definition(definition):
    if "x-kubernetes-group-version-kind" in definition:
        gvk = definition["x-kubernetes-group-version-kind"][0]
        group = gvk.get("group", "")
        version = gvk["version"]
        kind = gvk["kind"]
        
        # Construct apiVersion
        if group:
            api_version = f"{group}/{version}"
        else:
            api_version = version

        # Replace apiVersion and kind with constants
        if "properties" in definition:
            required = definition.setdefault("required", [])
            if "apiVersion" in definition["properties"]:
                definition["properties"]["apiVersion"]["enum"] = [api_version]
                definition["properties"]["apiVersion"]["default"] = api_version
                if "apiVersion" not in required:
                    required.append("apiVersion")
            if "kind" in definition["properties"]:
                definition["properties"]["kind"]["enum"] = [kind]
                definition["properties"]["kind"]["default"] = kind
                if "kind" not in required:
                    required.append("kind")
    # Convert int-or-string to string
    if "properties" in definition:
        for prop_name, prop in definition["properties"].items():
            if prop.get("format") == "int-or-string":
                prop["type"] = ["integer", "string"]
                prop.pop("format")


def main():
    # Fetch the swagger schema
    schema = fetch_swagger_schema()
    
    # Process each definition
    for definition_name, definition in schema["definitions"].items():
        process_definition(definition)
    # 
    renames = {}
    for definition_name, definition in schema["definitions"].items():
        # Remove the io.k8s.api prefix
        # If definition starts with io.k8s.apimachinery, replace the whole thing with just apimachinery
        # except the last part

        if definition_name.startswith("io.k8s.apimachinery."):
            *_, version, kind = definition_name.split(".")
            new_name = ["apimachinery"]
            new_name.append(kind)
            new_name = ".".join(new_name)
            renames[definition_name] = new_name
    

    for definition in list(schema["definitions"].keys()):
        if definition not in renames:
            schema["definitions"].pop(definition)

    # Rename the definitions
    for old_name, new_name in renames.items():
        schema["definitions"][new_name] = schema["definitions"].pop(old_name)
    # Change IntOrString to int | string
    for definition in schema["definitions"].values():
        if "format" in definition and definition["format"] == "int-or-string":
            definition["type"] = ["integer", "string"]
            definition.pop("format")
        if "properties" in definition:
            for prop in definition["properties"].values():
                if prop.get("format") == "int-or-string":
                    prop["type"] = ["integer", "string"]
                    prop.pop("format")
    output_schema = json.dumps(schema, indent=2)

    for rename in renames:
        # Replace refs like "#/definitions/core.v1.EndpointPort"
        output_schema = output_schema.replace(f'"#/definitions/{rename}"', f'"#/definitions/{renames[rename]}"')


    with open("processed_swagger.json", "w") as f:
        f.write(output_schema)



if __name__ == "__main__":
    main()