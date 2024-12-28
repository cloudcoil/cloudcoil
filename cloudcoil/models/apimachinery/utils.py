# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field, RootModel

from cloudcoil.client import BaseModel


class Quantity(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='Quantity is a fixed-point representation of a number. It provides convenient marshaling/unmarshaling in JSON and YAML, in addition to String() and AsInt64() accessors.\n\nThe serialization format is:\n\n``` <quantity>        ::= <signedNumber><suffix>\n\n\t(Note that <suffix> may be empty, from the "" case in <decimalSI>.)\n\n<digit>           ::= 0 | 1 | ... | 9 <digits>          ::= <digit> | <digit><digits> <number>          ::= <digits> | <digits>.<digits> | <digits>. | .<digits> <sign>            ::= "+" | "-" <signedNumber>    ::= <number> | <sign><number> <suffix>          ::= <binarySI> | <decimalExponent> | <decimalSI> <binarySI>        ::= Ki | Mi | Gi | Ti | Pi | Ei\n\n\t(International System of units; See: http://physics.nist.gov/cuu/Units/binary.html)\n\n<decimalSI>       ::= m | "" | k | M | G | T | P | E\n\n\t(Note that 1024 = 1Ki but 1000 = 1k; I didn\'t choose the capitalization.)\n\n<decimalExponent> ::= "e" <signedNumber> | "E" <signedNumber> ```\n\nNo matter which of the three exponent forms is used, no quantity may represent a number greater than 2^63-1 in magnitude, nor may it have more than 3 decimal places. Numbers larger or more precise will be capped or rounded up. (E.g.: 0.1m will rounded up to 1m.) This may be extended in the future if we require larger or smaller quantities.\n\nWhen a Quantity is parsed from a string, it will remember the type of suffix it had, and will use the same type again when it is serialized.\n\nBefore serializing, Quantity will be put in "canonical form". This means that Exponent/suffix will be adjusted up or down (with a corresponding increase or decrease in Mantissa) such that:\n\n- No precision is lost - No fractional digits will be emitted - The exponent (or suffix) is as large as possible.\n\nThe sign will be omitted unless the number is negative.\n\nExamples:\n\n- 1.5 will be serialized as "1500m" - 1.5Gi will be serialized as "1536Mi"\n\nNote that the quantity will NEVER be internally represented by a floating point number. That is the whole point of this exercise.\n\nNon-canonical values will still parse as long as they are well formed, but will be re-emitted in their canonical form. (So always use canonical form, or don\'t diff.)\n\nThis format is intended to make it difficult to use these numbers without writing some sort of special handling code in the hopes that that will cause implementors to also use a fixed point implementation.'
        ),
    ]


class RawExtension(BaseModel):
    pass


class IntOrString(RootModel[Union[int, str]]):
    root: Annotated[
        Union[int, str],
        Field(
            description="IntOrString is a type that can hold an int32 or a string.  When used in JSON or YAML marshalling and unmarshalling, it produces or consumes the inner type.  This allows you to have, for example, a JSON field that can accept a name or number."
        ),
    ]


class Info(BaseModel):
    build_date: Annotated[str, Field(alias="buildDate")]
    compiler: str
    git_commit: Annotated[str, Field(alias="gitCommit")]
    git_tree_state: Annotated[str, Field(alias="gitTreeState")]
    git_version: Annotated[str, Field(alias="gitVersion")]
    go_version: Annotated[str, Field(alias="goVersion")]
    major: str
    minor: str
    platform: str
