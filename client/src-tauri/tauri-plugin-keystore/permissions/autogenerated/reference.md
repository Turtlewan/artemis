## Default Permission

Default Artemis keystore permissions: webviews may sign and read public key state only.

#### This default permission set includes the following:

- `allow-sign`
- `allow-get-public-key`
- `allow-has-key`

## Permission Table

<table>
<tr>
<th>Identifier</th>
<th>Description</th>
</tr>


<tr>
<td>

`keystore:allow-create-key`

</td>
<td>

Enables the create_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:deny-create-key`

</td>
<td>

Denies the create_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:allow-destroy-key`

</td>
<td>

Enables the destroy_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:deny-destroy-key`

</td>
<td>

Denies the destroy_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:allow-get-public-key`

</td>
<td>

Enables the get_public_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:deny-get-public-key`

</td>
<td>

Denies the get_public_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:allow-has-key`

</td>
<td>

Enables the has_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:deny-has-key`

</td>
<td>

Denies the has_key command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:allow-sign`

</td>
<td>

Enables the sign command without any pre-configured scope.

</td>
</tr>

<tr>
<td>

`keystore:deny-sign`

</td>
<td>

Denies the sign command without any pre-configured scope.

</td>
</tr>
</table>
